"""Gen 4 pack generator controls (card C1-2).

Rule (tests/TESTING.md): an ABSENT input skips and names the artifact; a PRESENT-but-WRONG one
fails. The synthetic controls always run; the real-ROM/xMAP checks skip when an input is absent.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

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
    assert t["profile"]["party_off"] is None and t["profile"]["box_modified_flag_off"] is None
    assert "party_off" in t["open"] and "box_modified_flag_off" in t["open"] and "hge_internal_overlay_loads" in t["open"]
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
    with pytest.raises(g.Fail, match="sha1 mismatch"):
        g.verify_rom(inputs, _lock_for(data), "heartgold")
    path.write_bytes(data)
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
