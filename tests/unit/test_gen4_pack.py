"""Gen 4 pack generator controls (card C1-2).

Rule (tests/TESTING.md): an ABSENT input skips and names the artifact; a PRESENT-but-WRONG one
fails. The synthetic controls always run; the real-ROM/xMAP checks skip when an input is absent.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import struct
from pathlib import Path

import pytest

from tools import gen_gen4_pack as g

PACKS = {m: g.OUT[m] for m in ("hgss", "hge", "pt")}


def _need(*keys: str) -> g.Inputs:
    inputs = g.default_inputs()
    for key in keys:
        if not inputs.paths[key].is_file():
            pytest.skip(f"absent input {key}: {inputs.paths[key]}")
    return inputs


def _pack(mode: str) -> dict:
    return json.loads(PACKS[mode].read_text(encoding="utf-8"))


# ---- synthetic world: tiny xMAP + tiny images --------------------------------------------------
XMAP = """\
# .main
#>02000000          SDK_STATIC_START (linker command file)
  02000000 00000020 .text   FuncArm\t(a.o)
  02000000 00000000 .text   $a\t(a.o)
  02000100 00000010 .text   FuncThumb\t(a.o)
  02000100 00000000 .text   $t\t(a.o)
  02000200 00000010 .text   FuncData\t(a.o)
  02000200 00000000 .text   $d\t(a.o)
#>02000400          SDK_STATIC_END (linker command file)

# .OVY_12
#>0000000C          SDK_OVERLAY_OVY_12_ID (linker command file)
#>02000800          SDK_OVERLAY.OVY_12.START (linker command file)
  02000820 00000010 .text   Faint\t(b.o)
  02000820 00000000 .text   $t\t(b.o)

# .OVY_57
#>00000039          SDK_OVERLAY_OVY_57_ID (linker command file)
#>02000800          SDK_OVERLAY.OVY_57.START (linker command file)
  02000820 00000010 .text   Impostor\t(c.o)
  02000820 00000000 .text   $t\t(c.o)
"""
ARM9 = bytearray(0x400)
ARM9[0x100:0x110] = bytes.fromhex("70b50d1c061c281c012107f067f9281c")
ARM9[0:4] = bytes.fromhex("70402de9")  # ARM, AL condition
OV12 = bytearray(0x100)
OV12[0x20:0x30] = bytes.fromhex("004b1847d1ed3c02012107f067f9281c")


def _images() -> g.Images:
    return g.Images(0x02000000, bytes(ARM9), {12: (0x02000800, bytes(OV12), 0), 57: (0x02000800, bytes(0x100), 0)})


def _site(sid="faint", sym="Faint", image="ov12", addr=0x02000820, mode="thumb", n=16, ovl=12, images=None):
    reg = (images or _images()).read(image, addr, n).hex()
    return {sid: {"symbol": sym, "address": addr, "image": image, "overlay_id": ovl, "extent": n,
                  "register_hex": reg, "fire_hex": g.fire_hex(reg), "mode": mode}}


def test_xmap_owner_is_the_section_not_the_address():
    xm = g.XMap(XMAP)
    assert xm.lookup("Faint").address == xm.lookup("Impostor").address == 0x02000820
    assert (xm.lookup("Faint").image, xm.lookup("Impostor").image) == ("ov12", "ov57")
    assert xm.lookup("FuncArm").image == "arm9" and xm.static_end == 0x02000400
    assert (xm.mode(xm.lookup("FuncArm")), xm.mode(xm.lookup("FuncThumb"))) == ("arm", "thumb")
    with pytest.raises(g.Fail, match="FuncData"):  # a $d (literal pool) label is not a code mode
        xm.mode(xm.lookup("FuncData"))
    with pytest.raises(g.Fail, match="Nope"):
        xm.lookup("Nope")


def test_images_read_by_declared_image_and_report_collisions():
    img = _images()
    assert img.read("ov12", 0x02000820, 4) == OV12[0x20:0x24]
    assert img.read("ov57", 0x02000820, 4) == bytes(4)  # same address, different overlay
    assert img.collisions("ov12", 0x02000820, 16) == ["ov57"]
    with pytest.raises(g.Fail, match="does not contain"):
        img.read("arm9", 0x02000820, 16)  # ARM9 static ends at 0x02000400
    with pytest.raises(g.Fail):
        img.read("ov12", 0x020008F8, 16)  # extent runs off the end of the image


def test_valid_site_set_is_green():
    sites = {**_site(), **_site("arm", "FuncArm", "arm9", 0x02000000, "arm", 4, None)}
    assert g.validate_sites(sites, _images(), "t") == []


def test_wrong_declared_image_goes_red():
    # an ov12 site resolved from ARM9: not even inside it
    bad = _site()
    bad["faint"]["image"], bad["faint"]["overlay_id"] = "arm9", None
    assert any("does not contain" in e for e in g.validate_sites(bad, _images(), "t"))
    # an ov12 site declared as the other overlay that shares the address: bytes differ
    bad = _site()
    bad["faint"]["image"], bad["faint"]["overlay_id"] = "ov57", 57
    assert any("differs from the declared image" in e for e in g.validate_sites(bad, _images(), "t"))
    # a zero-padded expanded ARM9 (the hge bug): address-first would read zeros and call it a pin
    big = g.Images(0x02000000, bytes(0x1000), {12: (0x02000800, bytes(OV12), 0)})
    assert g.validate_sites(_site("faint", images=big), big, "t") == []
    wrong = _site("faint", images=big)
    wrong["faint"]["image"], wrong["faint"]["overlay_id"] = "arm9", None
    assert any("differs from the declared image" in e for e in g.validate_sites(wrong, big, "t"))


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s.update(register_hex="ff" + s["register_hex"][2:]), "differs from the declared image"),
    (lambda s: s.update(fire_hex=s["fire_hex"][:6]), "fire_hex"),  # 3 bytes
    (lambda s: s.update(fire_hex=s["fire_hex"] + "00"), "fire_hex"),  # 5 bytes
    (lambda s: s.update(fire_hex="".join(reversed([s["fire_hex"][i:i + 2] for i in range(0, 8, 2)]))), "fire_hex"),
    (lambda s: s.update(extent=8), "extent"),
    (lambda s: s.update(mode="arm"), "ARM site"),  # Thumb bytes declared ARM
    (lambda s: s.update(mode="bogus"), "mode"),
    (lambda s: s.update(overlay_id=57), "overlay_id"),
])
def test_mutated_pin_or_fire_word_goes_red(mutate, needle):
    sites = _site()
    mutate(sites["faint"])
    errs = g.validate_sites(sites, _images(), "t")
    assert errs and any(needle in e for e in errs), errs


def test_fire_hex_is_the_little_endian_u32():
    assert g.fire_hex("70b50d1c061c281c") == "1c0db570"
    assert g.extent_for(2) == 4 and g.extent_for(0x100) == 16 and g.extent_for(8) == 8


def test_hge_redirect_decoding():
    # vanilla ov12 BtlCmd_TryFaintMon entry in the pinned hge build -> ov130 replacement (offsets.ini:91)
    r = g.decode_redirect(0x0223E22C, bytes.fromhex("004b1847d1ed3c02012107f067f9281c"))
    assert r == {"kind": "ldr_bx_trampoline", "target": 0x023CEDD0, "thumb": True}
    # 0x1C-byte stub that saves lr and BLs the replacement
    r = g.decode_redirect(0x02073CC0, bytes.fromhex("60b4044d76462e6060bc68f39df901490847") + bytes(10))
    assert r["kind"] == "bl_stub" and r["target"] == 0x023DC008
    assert g.decode_redirect(0x02000000, bytes.fromhex("70b50d1c061c281c") + bytes(8)) is None


# ---- HG vs SS ----------------------------------------------------------------------------------
def _hgss_pair():
    pack = _pack("hgss")
    return copy.deepcopy(pack["titles"]["heartgold"]), copy.deepcopy(pack["titles"]["soulsilver"])


def test_committed_hg_ss_agree_and_mismatches_go_red():
    hg, ss = _hgss_pair()
    assert g.validate_hg_ss(hg, ss) == []
    ss["symbols"]["Party_AddMon"]["address"] += 2  # a gameplay symbol moved in SS
    assert any("Party_AddMon" in e for e in g.validate_hg_ss(hg, ss))
    hg, ss = _hgss_pair()
    ss["symbols"]["BtlCmd_TryFaintMon"]["image"] = "ov13"
    assert any("BtlCmd_TryFaintMon" in e for e in g.validate_hg_ss(hg, ss))
    hg, ss = _hgss_pair()
    ss["sites"]["battle_faint_cmd"]["register_hex"] = "00" * 16
    assert any("battle_faint_cmd" in e for e in g.validate_hg_ss(hg, ss))
    hg, ss = _hgss_pair()  # the ov74 menu site may differ in bytes per title, but not in address
    ss["sites"]["menu_only_ov74"]["register_hex"] = "00" * 16
    assert g.validate_hg_ss(hg, ss) == []
    ss["sites"]["menu_only_ov74"]["address"] += 2
    assert any("menu_only_ov74" in e for e in g.validate_hg_ss(hg, ss))
    hg, ss = _hgss_pair()
    ss["overlays"]["12"]["ram"] += 0x20
    assert any("overlay 12" in e for e in g.validate_hg_ss(hg, ss))


# ---- committed packs: shape without any ROM ----------------------------------------------------
@pytest.mark.parametrize("mode", ["hgss", "hge", "pt"])
def test_committed_pack_shape(mode):
    pack = _pack(mode)
    assert pack["schema"] == "gen4-profile-v1" and pack["generator"] == "tools/gen_gen4_pack.py"
    assert re.fullmatch(r"[0-9a-f]{64}", pack["provenance"]["lock"]["sha256"])
    for title, t in pack["titles"].items():
        assert re.fullmatch(r"[0-9a-f]{40}", t["rom"]["sha1"]) and re.fullmatch(r"[0-9a-f]{32}", t["rom"]["md5"])
        assert t["overlay_table"]["entry_size"] == 8 and t["overlay_table"]["regions"] == 3
        for sid, s in t["sites"].items():
            reg = bytes.fromhex(s["register_hex"])
            assert s["extent"] == len(reg) >= 4, (title, sid)
            assert re.fullmatch(r"[0-9a-f]{8}", s["fire_hex"]) and s["fire_hex"] == g.fire_hex(s["register_hex"])
            assert s["phase"] in ("always", "battle", "pc", "field", "probe"), (title, sid)
            if s["overlay_id"] is not None:  # the declared overlay's RAM span holds the whole extent
                ov = t["overlays"][str(s["overlay_id"])]
                assert ov["ram"] <= s["address"] and s["address"] + s["extent"] <= ov["ram"] + ov["size"], (title, sid)
                assert s["image"] == f"ov{s['overlay_id']}"
        for name, sym in t["symbols"].items():
            assert sym["image"] in ("arm9", "arm9_itcm", "arm9_dtcm") or sym["image"] in {f"ov{i}" for i in t["overlays"]}, name
        for note in t["open"].values():
            assert isinstance(note, str) and note


def test_committed_hgss_required_contents():
    pack = _pack("hgss")
    for title in ("heartgold", "soulsilver"):
        t = pack["titles"][title]
        for name in ("sSaveDataPtr", "sFieldSysPtr", "sOverlayRegions", "gSystem", "HandleLoadOverlay", "UnloadOverlayByID",
                     "Main_RunOverlayManager", "OS_WaitIrq", "OS_Halt", "VBlankCB_DmaTasksFramecounter", "Task_Blackout",
                     "Encounter_GetResult", "Party_AddMon", "PCStorage_PlaceMonInBoxFirstEmptySlot",
                     "PCStorage_PlaceMonInFirstEmptySlotInAnyBox", "PCStorage_SwapMonsInBoxByIndexPair",
                     "PCStorage_DeleteBoxMonByIndexPair", "Save_WriteManFinish", "BtlCmd_TryFaintMon", "DoSoftReset",
                     "sRTCWork", "ov12_02238A68"):
            assert name in t["symbols"], name
        assert t["symbols"]["sSaveDataPtr"]["address"] == 0x021D2228
        assert t["symbols"]["BtlCmd_TryFaintMon"]["image"] == "ov12"
        assert t["sites"]["battle_faint_cmd"]["overlay_id"] == 12 and t["sites"]["menu_only_ov74"]["overlay_id"] == 74
        assert {t["sites"][k]["mode"] for k in ("per_frame_arm", "per_frame_thumb")} == {"arm", "thumb"}
        prof = t["profile"]
        assert prof["battle"]["mons_off"] == 0x2D40 and prof["battle"]["ability_off"] == 0x27
        assert (prof["boxes"], prof["mons_per_box"], prof["memorial_box"]) == (18, 30, 17)
        assert prof["save"]["array_headers_off"] == 0x23014 and prof["save"]["slot_specs_off"] == 0x232B4


def test_committed_hge_and_pt_open_fields_are_explicit():
    hge = _pack("hge")
    assert hge["artifact_status"] == "RECORDED_NOT_ADMITTED"
    t = hge["titles"]["heartgold_hge"]
    assert t["profile"]["box_modified_flag_off"] is None  # needs a PHYSICAL mutation/save/reload
    assert "box_modified_flag_off" in t["open"] and "hge_internal_overlay_loads" in t["open"]
    # resolved by the populated owner save: the party header is FILE-confirmed, the trainer is the vanilla layout
    po = t["profile"]["party_off"]
    assert (po["value"], po["max_off"], po["count_off"], po["mons_off"], po["array_id"]) == (0x90, 0, 4, 8, 2)
    assert "party_off" not in t["open"] and "trainer" not in t["open"] and "0xCAB4" in po["evidence"]["rejected_candidate"]
    assert t["profile"]["trainer"]["array_id"] == 1 and t["profile"]["trainer"]["identity"]["general_off_of_profile"] == 0x64
    assert (t["profile"]["boxes"], t["profile"]["memorial_box"], t["profile"]["pkm"]["exp_bits"]) == (30, 29, 21)
    assert (t["profile"]["battle"]["ability_off"], t["profile"]["battle"]["ability_width"]) == (0x7A, 2)
    assert t["sites"]["battle_faint_cmd"]["image"] == "ov130" and t["sites"]["battle_faint_cmd"]["address"] == 0x023CEDD0
    assert t["sites"]["load_overlay_entry"]["image"] == "ov129"
    assert "not a fresh build association" in hge["provenance"]["hge_build"]["note"]
    pt = _pack("pt")
    assert pt["artifact_status"] == "BIND_ONLY_NOT_ADMITTED"
    p = pt["titles"]["platinum"]
    assert p["symbols"]["sSaveDataPtr"]["address"] == 0x021C0794 and p["overlay_table"]["address"] == 0x021BF370
    assert p["profile"]["pc"]["modified_flag_off"] is None and p["profile"]["dirty"]["full_save_flag"]["off"] == 0x0C
    assert p["profile"]["memorial_box"] is None and "memorial_box" in p["open"] and p["sites"] == {}


# ---- identity: absent skips, present-but-wrong fails -------------------------------------------
def _rom_file(tmp_path, payload=b"x" * 64, header=b"IPKE"):
    path = tmp_path / "r.nds"
    data = bytearray(payload)
    data[12:16] = header
    path.write_bytes(data)
    return path, bytes(data)


def _lock_for(data: bytes, header="IPKE"):
    return {"artifacts": {"heartgold": {"sha1": hashlib.sha1(data).hexdigest(), "md5": hashlib.md5(data).hexdigest(),
                                         "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                                         "header_code": header}}}


def test_absent_input_is_a_named_skip(tmp_path):
    inputs = g.Inputs({"heartgold": tmp_path / "missing.nds"}, lock=tmp_path / "lock.json")
    with pytest.raises(g.Skip, match="heartgold"):
        g.verify_rom(inputs, {}, "heartgold")
    with pytest.raises(g.Skip, match="lock file"):
        g.load_lock(inputs)
    assert g.main(["hgss", "--path", f"heartgold={tmp_path / 'missing.nds'}", "--check"]) == g.EXIT_SKIP


def test_present_but_wrong_rom_fails(tmp_path):
    path, data = _rom_file(tmp_path)
    inputs = g.Inputs({"heartgold": path})
    assert g.verify_rom(inputs, _lock_for(data), "heartgold")["header_code"] == "IPKE"
    path.write_bytes(data[:30] + b"Z" + data[31:])  # one byte flipped
    os.utime(path, ns=(0, path.stat().st_mtime_ns + 1_000_000))  # the digest cache is keyed by (mtime, size): a same-tick rewrite would hit it
    with pytest.raises(g.Fail, match="sha1 mismatch"):
        g.verify_rom(inputs, _lock_for(data), "heartgold")
    path.write_bytes(data)
    os.utime(path, ns=(0, path.stat().st_mtime_ns + 2_000_000))
    with pytest.raises(g.Fail, match="header"):
        g.verify_rom(inputs, _lock_for(data, header="IPGE"), "heartgold")


def test_cli_present_wrong_rom_exits_1(tmp_path):
    wrong, _ = _rom_file(tmp_path)  # a present ROM whose hash is not the locked one (needs only the lock)
    assert g.main(["hgss", "--path", f"heartgold={wrong}"]) == g.EXIT_FAIL


# ---- real inputs: regenerate and compare --------------------------------------------------------
@pytest.mark.parametrize("mode,keys", [
    ("hgss", ("heartgold", "soulsilver", "heartgold_xmap", "soulsilver_xmap")),
    ("hge", ("heartgold", "heartgold_hge", "heartgold_xmap", "hge_offsets", "hge_rom_gen_ld", "hge_nm_all")),
    ("pt", ("platinum", "platinum_xmap")),
])
def test_regeneration_matches_committed_and_sites_resolve(mode, keys, tmp_path):
    inputs = _need(*keys)
    text = g.generate(mode, inputs)
    assert text == PACKS[mode].read_text(encoding="utf-8"), f"{mode} pack drifted; run tools/gen_gen4_pack.py {mode}"
    # --check: clean copy exits 0; a mutated copy (drift) exits 1
    copy_path = tmp_path / "profile.json"
    copy_path.write_text(text, encoding="utf-8")
    assert g.main([mode, "--check", "--out", str(copy_path)]) == g.EXIT_OK
    pack = json.loads(text)
    first = next(iter(pack["titles"].values()))
    first["symbols"][next(iter(first["symbols"]))]["address"] += 4
    copy_path.write_text(g.render(pack), encoding="utf-8")
    assert g.main([mode, "--check", "--out", str(copy_path)]) == g.EXIT_FAIL
    copy_path.unlink()
    assert g.main([mode, "--check", "--out", str(copy_path)]) == g.EXIT_FAIL  # missing committed file is drift


def test_committed_sites_match_real_images():
    inputs = _need("heartgold", "soulsilver", "heartgold_hge")
    pack = _pack("hgss")
    for title in ("heartgold", "soulsilver"):
        assert g.validate_sites(pack["titles"][title]["sites"], g.load_images(inputs.paths[title]), title) == []
    hge = _pack("hge")["titles"]["heartgold_hge"]
    images = g.load_images(inputs.paths["heartgold_hge"], raw_arm9=True)
    assert g.validate_sites(hge["sites"], images, "hge") == []
    # control: the vanilla ov12 address read from hge's (expanded) ARM9 is not the declared image
    vanilla = pack["titles"]["heartgold"]["sites"]["battle_faint_cmd"]
    assert images.read("arm9", vanilla["address"], 16) != bytes.fromhex(vanilla["register_hex"])
    wrong = {"battle_faint_cmd": {**vanilla, "image": "arm9", "overlay_id": None}}
    assert g.validate_sites(wrong, images, "hge")


def test_xmap_static_end_and_overlay_starts_match_rom():
    inputs = _need("heartgold", "heartgold_xmap")
    xm, images = g.load_xmap(inputs.paths["heartgold_xmap"]), g.load_images(inputs.paths["heartgold"])
    g.check_xmap_vs_rom(xm, images, "heartgold")
    xm.overlay_start["ov12"] += 0x20  # control: a map that disagrees with the ROM table must fail
    try:
        with pytest.raises(g.Fail, match="START"):
            g.check_xmap_vs_rom(xm, images, "heartgold")
    finally:
        xm.overlay_start["ov12"] -= 0x20  # the parse is cached across tests


# ---- probe_field / system offsets for the C1-1 probe -------------------------------------------
PROBE_KEYS = {"sub", "save", "task", "live", "launched_app", "field_app", "paused", "save_driver", "save_state"}


def test_hgss_probe_field_values_types_and_evidence():
    for title in ("heartgold", "soulsilver"):
        prof = _pack("hgss")["titles"][title]["profile"]
        pf = prof["probe_field"]
        assert set(pf) >= PROBE_KEYS and all(isinstance(pf[k], int) and not isinstance(pf[k], bool) for k in PROBE_KEYS)
        assert pf == {**pf, "sub": 0x00, "save": 0x0C, "task": 0x10, "live": 0x6C, "launched_app": 0x04, "field_app": 0x00,
                      "paused": 0x08, "save_driver": 0xD8, "save_state": 0x01, "save_driver_data_off": 0x10}
        ev = prof["probe_field_evidence"]
        for key in pf:
            assert ev[key]["class"] in ("SOURCE", "ASM") and "pokeheartgold@" in ev[key]["cite"], key
        for key in ("save", "live", "save_driver", "save_state"):  # asm-corroborated
            assert ev[key]["class"] == "ASM" and "asm/overlay_01_" in ev[key]["cite"], key
        assert prof["system"]["vblank_counter_off"] == 0x2C
        off = prof["probe_wrong_write_offset"]
        assert isinstance(off, int) and 0x6D <= off <= 0x6F  # compiler padding after softResetDisabled @0x6C
        assert "padding" in prof["probe_wrong_write_offset_evidence"]


def test_hge_probe_fields_are_vanilla_projections_and_pt_stays_open():
    hge = _pack("hge")["titles"]["heartgold_hge"]
    prof = hge["profile"]
    pf, ev = prof["probe_field"], prof["probe_field_evidence"]
    assert pf == _pack("hgss")["titles"]["heartgold"]["profile"]["probe_field"]  # same offsets as vanilla, none left null
    assert prof["system"]["vblank_counter_off"] == 0x2C
    assert ev["save"]["class"] == ev["task"]["class"] == "SOURCE"  # the only two the fork header declares
    for key in PROBE_KEYS - {"save", "task"}:
        assert ev[key]["class"] == "SOURCE_PROJECTION" and "probe_field_hge_checks" in ev[key]["cite"], key
    checks = prof["probe_field_hge_checks"]
    assert checks["field_system_new"]["alloc_size"] == 0x128
    assert {"FieldSystem_LaunchApplication", "OverlayManager_Run", "ov01_021F68DC", "Battle_Run"} <= {
        f["symbol"] for f in checks["functions_byte_identical"]}
    assert "probe_field" in hge["open"]  # still a PHYSICAL cell
    pt = _pack("pt")["titles"]["platinum"]
    assert pt["profile"]["probe_field"] is None and "probe_field" in pt["open"]
    assert pt["profile"]["probe_wrong_write_offset"] is None


def test_hge_hidden_ability_is_bit_6_of_the_two_bit_field_not_bit_0():
    ha = _pack("hge")["titles"]["heartgold_hge"]["profile"]["pkm"]["hidden_ability"]
    assert (ha["block"], ha["byte_off"], ha["field_bits"], ha["bit"], ha["mask"]) == ("B", 0x19, [6, 7], 6, 0x40)
    assert ha["mask"] == 1 << ha["bit"] and "Leaf Crown" in ha["note"] and "FILE" in ha["evidence"]
    assert "hidden_ability" not in _pack("hgss")["titles"]["heartgold"]["profile"]["pkm"]


# ---- Part A data gaps: location / Pt party+trainer+footer / hge party+trainer ---------------------------
SAVES = Path("C:/slink/g4/saves")
SAVE_OF = {"hgss": ("hg_base_26310.SaveRAM", "hgss"), "hge": ("hge_a_OOO_630.SaveRAM", "hge"), "pt": ("pt_TTT_44361.SaveRAM", "pt")}


def _general(mode: str) -> bytes:
    name, variant = SAVE_OF[mode]
    if not (SAVES / name).is_file():
        pytest.skip(f"absent input save: {SAVES / name}")
    from server.adapters.gen4_codec import parse_save
    return parse_save((SAVES / name).read_bytes(), variant).general


def _profile(mode: str) -> dict:
    title = {"hgss": "heartgold", "hge": "heartgold_hge", "pt": "platinum"}[mode]
    return _pack(mode)["titles"][title]["profile"]


@pytest.mark.parametrize("mode", ["hgss", "hge", "pt"])
def test_location_offsets_match_the_20_byte_location_struct(mode):
    prof = _profile(mode)
    loc = prof["location"]
    offs = [loc[k] for k in ("map_off", "warp_off", "x_off", "y_off", "dir_off")]
    assert loc["struct_size"] == 20 == 5 * 4 and offs == [0, 4, 8, 12, 16]  # 5 x s32, packed, in struct order
    assert all(o % 4 == 0 and o + 4 <= loc["struct_size"] for o in offs) and len(set(offs)) == 5
    ids = prof["save"]["array_ids"]
    assert loc["array_id"] == ids["field_overworld_state" if mode == "pt" else "local_field_data"] == (11 if mode == "pt" else 5)
    assert loc["evidence"].startswith("SOURCE") and loc["file_cross_check"]["general_off_of_array"] > 0
    assert (loc.get("y_field") == "z") == (mode == "pt")


@pytest.mark.parametrize("mode", ["hgss", "hge", "pt"])
def test_pack_offsets_decode_the_owner_saves(mode):
    """FILE: the pack's own numbers applied to the real saves give the known party header, identity and a real Location."""
    prof, general = _profile(mode), _general(mode)
    po = prof["party_off"]
    assert struct.unpack_from("<II", general, po["value"]) == (6, 1) and (po["max_off"], po["count_off"], po["mons_off"]) == (0, 4, 8)
    tr, loc = prof["trainer"], prof["location"]
    base = tr["identity"]["general_off_of_profile"]
    assert base == tr["identity"]["id_general_off"] - tr["id_off"] == (0x68 if mode == "pt" else 0x64)
    assert struct.unpack_from("<I", general, base + tr["id_off"])[0] & 0xFFFF == {"hgss": 26310, "hge": 630, "pt": 44361}[mode]
    assert general[base + tr["version_off"]] == {"hgss": 7, "hge": 7, "pt": 12}[mode]
    map_id, warp, x, y, d = struct.unpack_from("<5i", general, loc["file_cross_check"]["general_off_of_array"])
    assert 0 < map_id < 1000 and -1 <= warp < 50 and 0 < x < 3000 and 0 < y < 3000 and -1 <= d <= 3


def test_pt_footer_formula_matches_the_real_general_block_footer():
    sv = _profile("pt")["save"]
    ft, bi = sv["footer"], sv["block_info"]
    assert (ft["size"], ft["signature"], ft["block_count"]) == (0x14, 0x20060623, 2) and bi["entry_size"] == 0xC
    assert bi["table_off"] == sv["table_off"] + sv["entry_count"] * sv["entry_size"] == 0x20284
    assert "blockInfo[b].offset + blockInfo[b].size - size" in ft["addr"] and "block_id == b" in ft["valid_when"]
    general = _general("pt")  # block 0: offset 0, size == the general length, footer in its last 0x14 bytes
    foot, f = general[len(general) - ft["size"]:], ft["fields"]
    assert struct.unpack_from("<I", foot, f["signature"])[0] == ft["signature"]
    assert struct.unpack_from("<I", foot, f["size"])[0] == len(general) and foot[f["block_id"]] == ft["blocks"]["normal"]


# ---- G1 phase cases (row n) -----------------------------------------------------------------------------
def _title(mode: str = "hgss") -> dict:
    pack = _pack(mode)
    return copy.deepcopy(next(iter(pack["titles"].values())))


def _red(title: dict, needle: str) -> None:
    errs = g.validate_phase_cases(title)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("mode", ["hgss", "hge"])
def test_committed_phase_cases_validate_and_cover_the_candidates(mode):
    pack = _pack(mode)
    for name, t in pack["titles"].items():
        assert g.validate_phase_cases(t) == [], name
        assert [c["name"] for c in t["phase_cases"]] == ["battle", "battle_arm", "battle_disarm", "reset"]
        assert [c["name"] for c in t["phase_cases_blocked"]] == ["pc"]
        for phase in ("battle", "pc"):
            cases = [c for c in t["phase_cases"] + t["phase_cases_blocked"] if c["phase"] == phase]
            chosen = {s for c in cases for s in c["sites"]}
            skipped = set(t["phase_cases_excluded"][phase])
            assert chosen | skipped == set(t["phases"][phase]["candidate_sites"]) and not chosen & skipped, (name, phase)
            assert all(isinstance(why, str) and why for why in t["phase_cases_excluded"][phase].values())
        for c in t["phase_cases"]:
            assert c["predicate"] == {"symbol": "sFieldSysPtr", "deref": [0, 4], "offset": 0x0C, "value": 12}
            assert c["predicate_file_check"]["ovy_id"] == 12 and c["status"] == "ROUTE_LEGS_PARTLY_NEW"
            assert c["producer_site"] in c["sites"] and len(c["sites"]) + 1 <= 4 and c["open"]  # honest: nothing is closed
            assert c["route"][0] in ("gen4_routes:battle_settled",) and all(leg in c["route_status"] for leg in c["route"])
        pc = t["phase_cases_blocked"][0]
        assert pc["predicate"]["value"] == pc["predicate_file_check"]["ovy_id"] == 14 and pc["status"] == "BLOCKED_NO_FIXTURE"
        assert "1 party mon" in pc["blocked_reason"]


def test_hg_and_ss_phase_cases_are_identical():
    pack = _pack("hgss")
    hg, ss = pack["titles"]["heartgold"], pack["titles"]["soulsilver"]
    for key in ("phase_cases", "phase_cases_blocked", "phase_cases_excluded"):
        assert hg[key] == ss[key], key


def test_predicate_is_tied_to_the_probe_field_chain_and_the_rom_template():
    t = _title()
    pf = t["profile"]["probe_field"]
    assert all(c["predicate"]["deref"] == [pf["sub"], pf["launched_app"]] for c in t["phase_cases"])
    assert t["symbols"]["sFieldSysPtr"]["address"] == 0x021D4158 and "sFieldSysPtr" in t["symbols"]
    t["phase_cases"][0]["predicate"]["deref"] = [0, 8]
    _red(t, "probe_field")
    t = _title()
    t["phase_cases"][0]["predicate"]["value"] = 13  # the template in the ROM says 12
    _red(t, "ROM template ovy_id")
    t = _title()
    t["phase_cases"][0]["predicate"]["nonzero"] = True  # value AND nonzero is ambiguous
    _red(t, "exactly one of value / nonzero")


def test_wrong_predicate_symbol_goes_red():
    t = _title()
    t["phase_cases"][0]["predicate"]["symbol"] = "sNotInTheXmap"
    _red(t, "predicate.symbol")
    t = _title()
    t["phase_cases"][0]["predicate"]["symbol"] = "gSystem"  # a real xMAP symbol is accepted by this check (the chain check catches it)
    assert not any("predicate.symbol" in e for e in g.validate_phase_cases(t))


def test_sites_above_the_cap_go_red():
    t = _title()
    battle = t["phases"]["battle"]
    assert battle["cap"] == 3
    t["phase_cases"][0]["sites"] = [*battle["candidate_sites"][:4]]  # 4 candidates > cap 3
    _red(t, "exceed the battle cap 3")
    t = _title()
    t["phase_cases_blocked"][0]["sites"] = t["phases"]["pc"]["candidate_sites"][:3]  # cap 2
    _red(t, "exceed the pc cap 2")


def test_producer_must_be_one_of_the_armed_sites():
    # the probe compares its always-on observer with the REGISTRY events of producer_site, so a producer outside `sites` can never match
    t = _title()
    t["phase_cases"][0]["producer_site"] = "encounter_result"
    _red(t, "must be one of sites")


def test_case_site_outside_candidate_sites_goes_red():
    t = _title()
    t["phase_cases"][0]["sites"][1] = "pc_swap_by_index_pair"  # a pc candidate in a battle case
    _red(t, "is not a battle candidate_site")
    t = _title()
    t["phase_cases"][0]["sites"][1] = "per_frame_arm"  # a probe-phase site
    _red(t, "is not a battle candidate_site")


def test_every_unexercised_caller_must_be_listed_once_with_a_reason():
    t = _title()
    t["phase_cases"][0]["open"].pop()
    _red(t, "why_open")
    t = _title()
    row = t["phase_cases"][0]["caller_matrix"]["sites"][0]["callers"][0]
    row["exercised_by_route"], row["exercised_by"] = True, ["pc_exit_app"]  # claims coverage by a leg outside the route
    _red(t, "leg that is not in the route")
    t = _title()
    t["phase_cases"][0]["route"].append("teleport")  # a leg without a route_status
    _red(t, "named legs")
    t = _title()
    t["phase_cases"][0]["caller_matrix"]["sites"].pop()
    _red(t, "caller_matrix.sites")


# ---- card C1-2c: button-recipe route legs, UI geometry, shared-address collision pairs ------------
ALL_TITLES = [(mode, name) for mode in ("hgss", "hge") for name in _pack(mode)["titles"]]


def _tt(mode: str, name: str) -> dict:
    return copy.deepcopy(_pack(mode)["titles"][name])


def _red_legs(title: dict, needle: str) -> None:
    errs = g.validate_route_legs(title)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("mode,name", ALL_TITLES)
def test_committed_route_legs_validate_and_cover_every_named_leg(mode, name):
    t = _tt(mode, name)
    assert g.validate_route_legs(t) == [] and g.validate_collision_pairs(t) == []
    legs = t["route_legs"]
    for case in [*t["phase_cases"], *t["phase_cases_blocked"]]:
        assert set(case["route"]) <= set(legs), case["name"]
    assert set(t["route"]) | set(t["persistence_route"]) <= set(legs)
    recipes = {n for n, leg in legs.items() if leg["route_status"] == "recipe_source"}
    assert {"fight_until_enemy_faints", "run_from_wild", "exit_battle_to_overworld", "soft_reset_in_fight_menu", "open_start_menu",
            "start_menu_cursor_to_save", "start_menu_select_save", "save_confirm_until_saved", "close_start_menu"} == recipes
    assert all(legs[n]["steps"] == [] and legs[n]["until"] is None and legs[n]["open"] for n in set(legs) - recipes)
    assert all(legs[n]["evidence"] in ("SOURCE", "FILE") for n in recipes)
    buttons = {b for n in recipes for st in legs[n]["steps"] for b in st["press"]}
    assert buttons <= set(g.NDS_BUTTONS) and {"A", "X", "Start", "Select", "L", "R", "Up", "Down", "Left"} <= buttons


def test_hg_ss_hge_route_legs_and_collision_pairs_agree():
    hg, ss = _tt("hgss", "heartgold"), _tt("hgss", "soulsilver")
    for key in ("route_legs", "route", "persistence_route", "collision_pairs"):
        assert hg[key] == ss[key], key
    # the UI code is byte-identical across the two ROMs; only the compared-with label differs
    assert {n: r["sha1"] for n, r in hg["ui_geometry"]["code_identity"]["symbols"].items()} == \
        {n: r["sha1"] for n, r in ss["ui_geometry"]["code_identity"]["symbols"].items()}
    hge = _tt("hge", "heartgold_hge")
    for n, leg in hg["route_legs"].items():  # same recipes; only the hge note on the faint leg differs
        assert {k: v for k, v in hge["route_legs"][n].items() if k != "note"} == {k: v for k, v in leg.items() if k != "note"}, n
    assert hge["ui_geometry"]["code_identity"]["symbols"] == hg["ui_geometry"]["code_identity"]["symbols"]


def test_unknown_predicate_symbol_in_a_recipe_goes_red():
    t = _tt("hgss", "heartgold")
    t["route_legs"]["run_from_wild"]["until"]["symbol"] = "sNotInTheXmap"
    _red_legs(t, "until.symbol")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["run_from_wild"]["until"].update(nonzero=True)  # value|nonzero|zero must be exactly one
    _red_legs(t, "exactly one of value")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["run_from_wild"]["until"] = None
    _red_legs(t, "until must be a predicate object")


@pytest.mark.parametrize("bad", [None, 0, -5, g.ROUTE_MAX_FRAMES + 1, True, "600"])
def test_recipe_without_a_bounded_max_frames_goes_red(bad):
    t = _tt("hgss", "heartgold")
    t["route_legs"]["fight_until_enemy_faints"]["max_frames"] = bad
    _red_legs(t, "max_frames must be a bounded integer")
    t = _tt("hgss", "heartgold")
    del t["route_legs"]["fight_until_enemy_faints"]["max_frames"]
    _red_legs(t, "max_frames must be a bounded integer")


def test_a_cycle_longer_than_max_frames_and_bad_steps_go_red():
    t = _tt("hgss", "heartgold")
    t["route_legs"]["fight_until_enemy_faints"]["max_frames"] = 10
    _red_legs(t, "exceeds max_frames")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["open_start_menu"]["steps"][0]["press"] = ["Z"]  # not a BizHawk NDS joypad name
    _red_legs(t, "BizHawk NDS buttons")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["open_start_menu"]["steps"][0]["hold_frames"] = 0  # a press must be held at least one frame
    _red_legs(t, "hold_frames >= 1")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["open_start_menu"]["steps"] = []
    _red_legs(t, "needs steps")


def test_every_route_and_phase_case_leg_must_exist_in_route_legs():
    t = _tt("hgss", "heartgold")
    t["phase_cases"][0]["route"].append("teleport")
    _red_legs(t, "leg 'teleport' is not in route_legs")
    t = _tt("hgss", "heartgold")
    del t["route_legs"]["fight_until_enemy_faints"]  # still named by route and by phase_cases[].route
    errs = g.validate_route_legs(t)
    assert any("route:" in e for e in errs) and any("phase_case:battle.route" in e for e in errs), errs
    t = _tt("hgss", "heartgold")
    t["persistence_route"] = []
    _red_legs(t, "persistence_route")
    t = _tt("hgss", "heartgold")
    t["route_legs"]["gen4_routes:battle_settled"]["steps"] = [{"press": ["A"], "hold_frames": 1, "then_wait_frames": 1}]
    _red_legs(t, "an open leg keeps steps []")


def test_battle_dpad_recipes_follow_the_rom_tables_from_every_cursor_cell():
    ui = _tt("hgss", "heartgold")["ui_geometry"]
    main = ui["battle_main_cursor"]["cells"]
    assert main == g.EXPECT_MAIN_CURSOR and ui["battle_fight_cursor"]["cells"] == g.EXPECT_FIGHT_CURSOR
    step = lambda x, y, k: g.main_menu_step(main, x, y, k)  # noqa: E731
    starts = [(x, y) for y in range(2) for x in range(3)]
    assert {g._run(step, c, ui["battle_paths"]["to_FIGHT"]) for c in starts} == {(0, 0)}
    assert {main[y][x] for x, y in (g._run(step, c, ui["battle_paths"]["to_RUN"]) for c in starts)} == {3}
    # the quirks the recipes route around: Up on RUN does nothing; Left on FIGHT jumps to BAG (bottom-left)
    assert g.main_menu_step(main, 1, 1, "Up") == (1, 1) and g.main_menu_step(main, 0, 0, "Left") == (0, 1)
    fight = ui["battle_fight_cursor"]["cells"]
    fstep = lambda x, y, k: g._check_key(x, y, 2, 3, fight, k)  # noqa: E731
    assert {g._run(fstep, (x, y), ui["battle_paths"]["fight_to_MOVE_1"]) for y in range(3) for x in range(2)} == {(0, 0)}


def test_start_menu_save_path_is_the_bfs_over_the_rom_neighbour_table():
    sm = _tt("hgss", "heartgold")["ui_geometry"]["start_menu"]
    nav = sm["neighbour_table"]["rows"]
    assert len(nav) == 7 and all(len(row) == 4 and all(len(c) == 3 for c in row) for row in nav)
    assert sm["layout_rows"]["rows"][0] == g.FULL_MENU_VARIANT and sm["icon_order"][5] == "SAVE"
    assert sm["cursor_to_save"] == {**sm["cursor_to_save"], "from_cell": 0, "to_cell": 5, "path": ["Down", "Left"]}
    assert g.start_menu_path(nav, 0, 5) == ["Down", "Left"] and g.start_menu_path(nav, 5, 5) == []
    # no single word reaches SAVE from every start cell, which is why the leg verifies the landing cell
    assert g.start_menu_path(nav, 3, 5) == ["Left", "Up"] != g.start_menu_path(nav, 0, 5)
    leg = _tt("hgss", "heartgold")["route_legs"]["start_menu_cursor_to_save"]
    assert [st["press"] for st in leg["steps"]] == [[d] for d in sm["cursor_to_save"]["path"]]
    assert leg["until"]["value"] == 5 and leg["until"]["offset"] == g.PANEL_CURSOR_OFF
    assert g.start_menu_path([[[0, 0, 0]] * 4] * 7, 0, 5) is None  # a table without a route is None, not a guess


def test_save_and_battle_predicates_use_the_pack_probe_field_offsets():
    t = _tt("hgss", "heartgold")
    pf, legs = t["profile"]["probe_field"], t["route_legs"]
    chain = [pf["save_driver"], pf["save_driver_data_off"], 4, pf["save_driver_data_off"]]
    assert legs["start_menu_select_save"]["until"] == {"symbol": "sFieldSysPtr", "deref": chain, "offset": 0x0C, "value": 4}
    assert legs["save_confirm_until_saved"]["until"]["value"] == 15 and legs["save_confirm_until_saved"]["until"]["deref"] == chain
    assert legs["open_start_menu"]["until"] == {"symbol": "sFieldSysPtr", "deref": [], "offset": pf["task"], "nonzero": True}
    assert legs["exit_battle_to_overworld"]["until"]["zero"] is True and legs["run_from_wild"]["until"]["deref"] == [pf["sub"]]
    b = t["profile"]["battle"]
    assert legs["fight_until_enemy_faints"]["until"] == {
        "symbol": "sFieldSysPtr", "deref": [pf["sub"], pf["launched_app"], 0x1C, b["ctx_off"]],
        "offset": b["mons_off"] + b["mon_size"] + b["hp_off"], "zero": True}
    reset = legs["soft_reset_in_fight_menu"]
    assert reset["steps"][0]["press"] == ["Start", "Select", "L", "R"] and "NULL base" in reset["note"]


def test_collision_pair_shares_one_address_in_two_images_with_different_words():
    for mode, name in ALL_TITLES:
        t = _tt(mode, name)
        (pair,) = t["collision_pairs"]
        a, b = pair["sites"].values()
        assert a["address"] == b["address"] == pair["address"] == 0x021E5900
        assert {a["image"], b["image"]} == {"ov1", "ov60"} and a["fire_hex"] != b["fire_hex"]
        assert {a["symbol"], b["symbol"]} == {"FieldMap_VBlankCallback", "TitleScreen_Init"}
        assert t["overlays"]["1"]["ram"] == t["overlays"]["60"]["ram"] == pair["address"]
        assert g.validate_collision_pairs(t) == []
    hge = _tt("hge", "heartgold_hge")["collision_pairs"][0]
    assert "all zero padding" in hge["hge_note"] and hge["open"] == []


def test_collision_sites_in_the_same_image_or_at_different_addresses_go_red():
    t = _tt("hgss", "heartgold")
    sites = t["collision_pairs"][0]["sites"]
    sites["title_init_ov60"]["image"] = sites["field_vblank_ov1"]["image"]  # same owning image: not a collision
    assert any("different images" in e for e in g.validate_collision_pairs(t))
    t = _tt("hgss", "heartgold")
    t["collision_pairs"][0]["sites"]["title_init_ov60"]["address"] += 2
    assert any("share one address" in e for e in g.validate_collision_pairs(t))
    t = _tt("hgss", "heartgold")
    sites = t["collision_pairs"][0]["sites"]
    sites["title_init_ov60"]["fire_hex"] = sites["field_vblank_ov1"]["fire_hex"]
    assert any("first words must differ" in e for e in g.validate_collision_pairs(t))
    t = _tt("hgss", "heartgold")
    del t["collision_pairs"][0]["resident_when"]["title_init_ov60"]
    assert any("resident_when" in e for e in g.validate_collision_pairs(t))
    t = _tt("hgss", "heartgold")
    t["collision_pairs"] = []
    assert g.validate_collision_pairs(t) == ["collision_pairs missing or empty"]


def test_collision_sites_match_the_real_images():
    inputs = _need("heartgold", "soulsilver", "heartgold_hge")
    for mode, name, key, raw in (("hgss", "heartgold", "heartgold", False), ("hgss", "soulsilver", "soulsilver", False),
                                 ("hge", "heartgold_hge", "heartgold_hge", True)):
        images = g.load_images(inputs.paths[key], raw_arm9=raw)
        assert g.validate_sites(_tt(mode, name)["collision_pairs"][0]["sites"], images, name) == []


def test_the_synthetic_world_rejects_a_same_image_pair(monkeypatch):
    xm = g.XMap(XMAP)
    monkeypatch.setattr(g, "COLLISION_SPECS", [{"name": "synthetic", "sites": [("a", "Faint", "x"), ("b", "Faint", "x")]}])
    with pytest.raises(g.Fail, match="one address in two images"):
        g.collision_pairs(xm, _images(), "hgss")


def test_comparison_name_and_image_attribution_counts_reconcile():
    c = _pack("hgss")["comparison"]
    several = c["differing_names_in_several_images"]
    assert sum(c["differing_names_by_image"].values()) == c["differing_name_image_pairs"]
    assert c["differing_name_image_pairs"] == c["address_differs"] + len(several)  # each such name sits in exactly two images
    assert several == sorted(several) and c["address_differs"] > len(several)
    other = g.XMap(XMAP.replace("02000100 00000010 .text   FuncThumb", "02000104 00000010 .text   FuncThumb"))
    d = g.compare_title_maps(g.XMap(XMAP), other)
    assert d["address_differs"] == 1 == d["differing_name_image_pairs"] and d["differing_names_by_image"] == {"arm9": 1}


def test_probe_field_citations_point_at_the_lines_the_coordinator_checked():
    ev = _pack("hgss")["titles"]["heartgold"]["profile"]["probe_field_evidence"]
    assert "include/field_system.h:81 (FieldSystemUnkSub0.unk4" in ev["launched_app"]["cite"]
    assert "include/field_system.h:80 (FieldSystemUnkSub0.unk0" in ev["field_app"]["cite"]
    assert ":115-117 (sub_0203DF7C" in ev["field_app"]["cite"] and "97 (non-NULL for the whole field session" not in ev["field_app"]["cite"]


def test_source_citations_are_re_read_from_the_pinned_clone():
    clone = g.gen4_pins.default_locations().sources["pokeheartgold_citation"]
    if not (clone / "src" / "start_menu.c").is_file():
        pytest.skip(f"absent input pokeheartgold clone: {clone}")
    assert len(g.CITE_NEEDLES) > 40
    for path, line, needle in g.CITE_NEEDLES:
        text = (clone / path).read_text(encoding="utf-8", errors="replace").splitlines()
        assert line <= len(text) and needle in text[line - 1], f"{path}:{line} does not contain {needle!r}: {text[line - 1]!r}"
    # control: the pre-fix line (field_system.h:80 for unk4) does not carry unk4
    header = (clone / "include/field_system.h").read_text(encoding="utf-8").splitlines()
    assert "unk4" not in header[79] and "unk4" in header[80]
