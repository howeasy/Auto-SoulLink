"""A fake NDS + fake BizHawk + fake server that drives the PRODUCTION lua/gen4/client.lua.

One `World` is one cartridge + one client. Nothing here is PHYSICAL evidence: it is the offline
model the client's contracts are tested against (the live proof is the probe's job).

* main RAM is a sparse-by-construction 4 MiB bytearray; every struct the client reads is laid out
  through the pack's own profile fields (save array headers, party, PC boxes, the battle chain,
  the field-system chain, gSystem, the overlay table) and PK4 records come from the Python codec
  (server/adapters/gen4_codec.py), so the client's reads decode real records;
* vanilla admission runs against the pack's real ARM9 anchors;
* the fake `io` records every write as (frame, addr, width) in `World.writes` and every
  bus-exec registration in `World.hooks`; `World.dispatch` queues "the game ran the function at
  `addr` with r0/r1" for the next frame, fired BETWEEN the frame counter bump and `frame_end`
  (BizHawk's real order: the hook fires inside frameadvance, then the client's frame_end runs
  with the new framecount);
* every line the client sends is parsed and checked against tests/unit/protocol_schema.py (a
  problem raises at send time).

D7_MODEL below is a MODEL of profile.battle.d7 (the pack carries it since b8150e11; the client prefers the
pack's). It is used only when a test strips the pack block (no_pack_d7) or overrides it with `d7=`. The
PartyExtra geometry is the client's named default (PERFORMANCE_MAX 5, pret include/constants/pokemon.h:132);
`party_extra` overrides it and `party_array_size` sizes the party array.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import lupa.lua54 as lupa

from server.adapters import gen4_codec as codec
from tests.unit import protocol_schema as ps

ROOT = Path(__file__).resolve().parents[2]
BASE, SIZE = 0x02000000, 0x400000

FS, SUB, APP, MAN, BS, CTX = 0x022A01EC, 0x022A0334, 0x022A0400, 0x022A6B04, 0x022C020C, 0x022C32D8
DRV, DRV_DATA = 0x022A9000, 0x022A9100
SD = 0x022D0000
P0, P1 = 0x022C8000, 0x022C9000          # battle party copies: player, foe
TRAINER_OTID = 0x30391A5C

# HG and SS share ONE D7 block, and the pack proves that rather than asserting it: the generator
# FILE-reads the seam out of each title's OWN decompressed ov12 (tools/gen_gen4_pack.py:2134-2151,
# d7_file_checks(xm, images, build), fed the per-title images at :2718-2721) and both ROMs answer
# with the same address and the same four pin bytes -- titles.heartgold.profile.battle_d7_file_checks
# (data/games/gen4_hgss/profile.json:3027-3068) equals titles.soulsilver.profile.battle_d7_file_checks
# (:8717-8758) field for field, as do the two battle.d7 blocks they produce (:2991-3002, :8681-8692).
# The SS per-field receipts say it in words: "HG==SS bytes at the seam, the dispatch table and
# ov12_0224D540 are FILE-compared in the SS ROM" (:8862, :8871, :8880, :8889, :8898, :8907).
D7_HGSS = {"seam": {"cmd": 11, "overlay_id": 12, "addr": 0x0224A70C, "pin_hex": "f8b582b0"},
           "ctx_cmd_off": 8, "bs_party_off": 0x68, "party_hp_off": 0x8E, "repl_flag_off": 0x13C}
D7_MODEL = {  # MODEL: used only when a test strips the pack's battle.d7 (no_pack_d7) or overrides it
    "heartgold": D7_HGSS,
    "soulsilver": D7_HGSS,       # the proven-equal row above, NOT a second copy of HG's numbers
    "heartgold_hge": {"seam": {"cmd": 9, "overlay_id": 12, "table": 0x0226CA90,
                               "addr": 35951836, "pin_hex": "004a1047"},
                      "ctx_cmd_off": 8, "bs_party_off": 0x68, "party_hp_off": 0x8E, "repl_flag_off": 0x13C},
}
PACKS = {"heartgold": "gen4_hgss", "soulsilver": "gen4_hgss", "heartgold_hge": "gen4_hge"}
# Where the PC array sits in the general+pc save region, per title: (its offset inside the dynamic
# region, the bytes that follow the box records). The pack's `pc` block is the PC block's own geometry
# (box_base / box_stride / mon_stride / cur_box_off / wallpapers_off / size); the array's PLACE in the
# save is the runtime value the game writes into arrayHeaders + saveSlotSpecs, so the pack carries it
# as evidence prose rather than as a field. Both numbers are derived here, never copied:
#   offset = (the PC block's address in the save) - save.dynamic_region_off
#     HG    pc.evidence "PC block at SaveData+0xF710" (profile.json:3556) - 0x10 (save.
#           dynamic_region_off :3736) = 0xF700 -- and the HG battery save's own saveSlotSpecs[1]
#           .offset measures the same 0xF700 (open.slot_spec_runtime_values, :348, generated at
#           tools/gen_gen4_pack.py:923 and re-checked at tests/unit/test_gen4_reads_lua.py:462-463)
#     SS    the SAME two pack lines for SS: pc.evidence :9234 and dynamic_region_off :9414
#     hge   pc.evidence states a bank-relative block address ("PC block at bank+0x10000",
#           data/games/gen4_hge/profile.json:3796), not a SaveData offset; the model takes it as the
#           array offset verbatim.
#   extra = (the PC array's size) - boxes * 0x1000
#     HG    0x12300 -- the live hg_p2/savedata.bin arrayHeaders[41] (test_gen4_reads_lua.py:52-54,
#           cross-checked against the HG battery save at :462-463) -- minus 18 boxes * 0x1000 = 0x300
#     SS    identical pc block (:9226-9239 == :3548-3561, one emitted dict for both HGSS titles,
#           tools/gen_gen4_pack.py:903-907) and identical boxes (18, :9134) => 0x300. SOURCE
#           projection, NOT an SS measurement: the SS title's own open.soulsilver_save_offsets
#           (:6039) says "no owner SS save (D4): party_off / trainer FILE evidence is HeartGold
#           only". The one SS-specific PC fact is PHYSICAL and agrees --
#           pc.box_modified_flag_evidence (:9229) cites the SS route log at PC+0x12004, i.e.
#           box_base 0 + 18 * 0x1000.
#     hge   "size 0x1E4FC FILE" (gen4_hge :3796) - 30 boxes * 0x1000 = 0x4FC
PC_OFF = {
    "heartgold": (0xF700, 0x300),
    "soulsilver": (0xF700, 0x300),
    "heartgold_hge": (0x10000, 0x4FC),
}


def key_of(pid: int, otid: int = TRAINER_OTID) -> str:
    return f"{pid:08X}:{otid:08X}"


def plain_mon(pid, otid, species, level, hp, max_hp, moves=(33, 45, 0, 0), item=0, egg=False):
    """A complete plain PartyPokemon (0xEC) the codec can encrypt; every field the client's
    plausibility guards read is set."""
    p = bytearray(codec.PARTY_MON_SIZE)
    struct.pack_into("<I", p, 0, pid)
    struct.pack_into("<HHI", p, 8, species, item, otid)
    struct.pack_into("<I", p, 16, 135)                                   # exp
    p[0x15] = 0x41                                                       # ability
    for i, mv in enumerate(moves):
        struct.pack_into("<H", p, 0x28 + 2 * i, mv)
    struct.pack_into("<I", p, 0x38, (1 << 30) if egg else 0)             # ivword: egg bit
    p[0x8C] = level
    struct.pack_into("<HH", p, 0x8E, hp, max_hp)
    return bytes(p)


class Mon:
    """A party / box occupant; `plain()` is its PartyPokemon."""

    def __init__(self, pid, species=155, level=5, hp=20, max_hp=20, otid=TRAINER_OTID, moves=(33, 45, 0, 0),
                 item=0, egg=False):
        self.pid, self.otid, self.species, self.level, self.hp, self.max_hp = pid, otid, species, level, hp, max_hp
        self.moves, self.item, self.egg = moves, item, egg

    @property
    def key(self):
        return key_of(self.pid, self.otid)

    def plain(self):
        return plain_mon(self.pid, self.otid, self.species, self.level, self.hp, self.max_hp, self.moves, self.item,
                         self.egg)

    def party_raw(self):
        return codec.encrypt_party(self.plain())

    def box_raw(self):
        return codec.encrypt_box(self.plain()[:codec.BOX_MON_SIZE])


def to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: to_lua(lua, x) for k, x in v.items() if x is not None})
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


def py(v):
    if lupa.lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and keys == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in keys]
    return {k: py(v[k]) for k in keys}


class World:
    def __init__(self, title="heartgold", *, party=None, boxes=None, d7="model", connected=True, rom_hash=None,
                 start=True, pre=None, area_of=None, no_pack_d7=False, charmap=None, order="hook_new",
                 party_extra=None, party_array_size=0x5B4, patch_title=None, balls=None):
        self.title_name = title
        self.party_array_size = party_array_size
        self.balls = balls  # None keeps the historical unwired world; bool opts into the real producer.
        self.order = order          # "hook_new": the hook sees the NEW framecount; "hook_old": the OLD one
        self.reads = 0              # io read calls (the per-frame read budget)
        self.read_log = None        # when a list: every read address (which reads a code path makes)
        self.pack_name = PACKS[title]
        doc = json.loads((ROOT / f"data/games/{self.pack_name}/profile.json").read_text(encoding="utf-8"))
        self.title = doc["titles"][title]
        self.prof = self.title["profile"]
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.m = bytearray(SIZE)
        self.frame = 0
        self.connected = connected
        self.regs: dict[str, int] = {}
        self.hooks: dict[str, tuple] = {}      # handle -> (fn, addr, name)
        self.hook_registrations = 0
        self.serial = 0
        self.pending_dispatch: list[tuple] = []
        self.writes: list[tuple[int, int, int]] = []     # (frame, addr, width)
        self.drop_writes: set[int] = set()               # a write to one of these addresses is silently lost
        self.sent: list[dict] = []
        self.sent_frames: list[int] = []
        self.replies: list[str] = []
        self.logs: list[str] = []
        self.hud: list[tuple] = []
        self.party: list[Mon] = party if party is not None else [Mon(0x5A3C91E7, 155, 5, 20, 20)]
        self.boxes: dict[tuple[int, int], Mon] = dict(boxes or {})
        self.foe = Mon(0x01010101, 16, 3, 13, 13, otid=0x0000BEEF)
        self.btype = 0
        self.in_battle = False
        self.rom_hash = rom_hash or self.title["rom"]["md5"]
        self.json = self.lua.eval("dofile")((ROOT / "lua/json_codec.lua").as_posix())
        self.d7 = D7_MODEL[title] if d7 == "model" else d7
        if no_pack_d7:                                   # simulate the pre-pack-block gap
            self.title["profile"]["battle"].pop("d7", None)
        self._lay_out()
        if pre is not None:
            pre(self)
        self.io = self._make_io()
        self.net = self._make_net()
        self.hud_t = self._make_hud()
        self.Client = self.lua.eval("dofile")((ROOT / "lua/gen4/client.lua").as_posix())
        cfg = {
            "root": ROOT.as_posix(), "json": self.json, "io": self.io, "net": self.net, "hud": self.hud_t,
            "log": lambda s: self.logs.append(s), "player": "a", "rom_hash": self.rom_hash,
            "header_code": self.title["rom"]["header_code"],
        }
        ball_client = self.lua.table()
        if balls is not None:
            # Same late binding as run.lua: Inputs reads the public client seam, not a fake bag callable.
            Inputs = self.lua.eval("dofile")((ROOT / "lua/gen4/inputs.lua").as_posix())
            save_array = self.lua.eval("""function(holder)
                return function(id)
                    if not holder.client then return nil, "client_not_ready" end
                    return holder.client:save_array(id)
                end
            end""")(ball_client)
            producer = Inputs.has_pokeballs(self.lua.table_from({
                "root": ROOT.as_posix(), "json": self.json, "title": title,
                "pack_profile": f"data/games/{self.pack_name}/profile.json", "save_array": save_array,
            }))
            if isinstance(producer, tuple):
                raise ValueError(f"world bag producer refused: {producer[1]}")
            cfg["has_pokeballs"] = producer
        if self.d7 is not None:
            cfg["d7"] = to_lua(self.lua, self.d7)
        if area_of is not None:                          # Lua source: function(map_id, loc) -> area_id, loc_name
            cfg["area_of"] = self.lua.eval(area_of)
        if charmap is not None:
            cfg["charmap"] = to_lua(self.lua, charmap)
        if party_extra is not None:                      # an OVERRIDE of the default geometry (stride 5, after mons[6])
            cfg["party_extra"] = to_lua(self.lua, party_extra)
        if patch_title is not None:
            patch_title(self.title)
        if no_pack_d7 or patch_title is not None:
            cfg["title_profile"] = to_lua(self.lua, self.title)
        res = self.Client.new(self.lua.table_from(cfg))
        self.admit_why = None
        if isinstance(res, tuple):
            self.session, self.admit_why = res
        else:
            self.session = res
        ball_client.client = self.session
        if self.session is not None and start:
            self.session.start(self.session)

    # ── memory ──────────────────────────────────────────────────────────────────────
    def r(self, a, n):
        return int.from_bytes(self.m[a - BASE:a - BASE + n], "little")

    def w(self, a, v, n=4):
        self.m[a - BASE:a - BASE + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    def put(self, a, data):
        self.m[a - BASE:a - BASE + len(data)] = data

    def get(self, a, n):
        return bytes(self.m[a - BASE:a - BASE + n])

    def _lay_out(self):
        t, prof = self.title, self.prof
        w = self.w
        if self.pack_name == "gen4_hgss":                      # vanilla admission anchors (the pack's real bytes)
            for s in t["sites"].values():
                if s.get("image") == "arm9" and s.get("register_hex") and s.get("address"):
                    self.put(s["address"], bytes.fromhex(s["register_hex"]))
            for a in t.get("admission_anchors", []):
                self.put(a["address"], bytes.fromhex(a["hex"]))
        w(prof["fieldsys_ptr"]["address"], FS)
        w(prof["save_ptr"]["address"], SD)
        pf = prof["probe_field"]
        w(FS + pf["sub"], SUB)
        w(FS + pf["save"], SD)
        w(FS + pf["live"], 1)
        w(FS + pf["task"], 0)
        w(FS + pf["save_driver"], DRV)
        w(DRV + pf["save_driver_data_off"], DRV_DATA)
        self.m[DRV_DATA + pf["save_state"] - BASE] = 1
        w(SUB + pf["field_app"], APP)
        w(SUB + pf["launched_app"], 0)
        w(SUB + pf["paused"], 0)
        self.sys = prof["system"]["address"] + prof["system"]["vblank_counter_off"]
        w(self.sys, 1000)
        sv = prof["save"]
        general = 0xF628
        pc_off, pc_extra = PC_OFF[self.title_name]
        self.pc_size = prof["boxes"] * 0x1000 + pc_extra
        self.arrays = {1: (0x30, 0x60), 2: (self.party_array_size, 0x90), 5: (0x84, 0x1234), 41: (self.pc_size, pc_off)}
        if self.balls is not None:
            bag = prof["bag"]
            # Model allocation in unused general-block RAM; the real runtime header resolves its base.
            # Pocket/slot geometry and ids come exclusively from this title's committed pack.
            size = max(p["off"] + p["count"] * bag["ball_slot_size"] for p in bag["pocket_layout"].values()) + 8
            self.arrays[bag["array_id"]] = (size, 0x2000)
        self.dyn = SD + sv["dynamic_region_off"]
        for i, (size, off) in self.arrays.items():
            self.put(SD + sv["array_headers_off"] + i * sv["array_header_size"], struct.pack("<IIIHH", i, size, off, 0, 0))
        if self.balls:
            bag = prof["bag"]
            slot = self.dyn + self.arrays[bag["array_id"]][1] + bag["balls_pocket_off"]
            for name, value in (("id", bag["ball_ids"][0]), ("quantity", 1)):
                field = bag["slot_fields"][name]
                w(slot + field["off"], value, field["size"])
        spec = SD + sv["slot_specs_off"]
        self.put(spec, struct.pack("<BBHII", 0, 0, 0x10, 0, general))
        self.put(spec + 12, struct.pack("<BBHII", 1, 0x10, 0x13, pc_off, self.pc_size))
        cf = sv["chunk_footer"]
        self.put(self.dyn + general - cf["size"],
                 struct.pack("<IIIHH", 0, general, cf["magic"], sv["slots"]["general"], 0))
        # player profile: OTID, version
        tr = prof["trainer"]
        base = self.dyn + self.arrays[1][1] + tr["profile_off_in_array"]
        w(base + tr["id_off"], TRAINER_OTID)
        self.m[base + tr["version_off"] - BASE] = tr["version_values"].get(self.title_name.replace("_hge", ""), 7)
        for i, ch in enumerate((0x12, 0x13, 0x14)):
            w(base + tr["name_off"] + 2 * i, ch, 2)
        w(base + tr["name_off"] + 6, 0xFFFF, 2)
        loc = prof["location"]
        lbase = self.dyn + self.arrays[5][1]
        for k, v in zip(("map_off", "warp_off", "x_off", "y_off", "dir_off"), (60, 1, 10, 20, 1), strict=True):
            w(lbase + loc[k], v)
        self.write_party()
        self.write_boxes()
        self.set_overlay(12)
        seam = (self.d7 or self.prof["battle"].get("d7") or {}).get("seam")
        if seam and "table" in seam:        # hge dispatch table is provenance, not a runtime pin oracle
            self.w(seam["table"] + 4 * seam["cmd"], seam["addr"] | 1)
        if seam:
            self.put(seam["addr"], bytes.fromhex(seam["pin_hex"]))

    def write_party(self):
        base = self.dyn + self.arrays[2][1]
        self.w(base, 6)
        self.w(base + 4, len(self.party))
        for i, mon in enumerate(self.party):
            self.put(base + 8 + 0xEC * i, mon.party_raw())
        self.party_base = base
        for i in range(6):                                  # PartyExtra: 5 aprijuice bytes per slot, distinct per slot
            self.put(base + self.extra_off + 5 * i, bytes([0xA0 + 0x10 * i + k for k in range(5)]) if i < len(self.party) else bytes(5))

    def write_boxes(self):
        pc = self.prof["pc"]
        self.pc_base = self.dyn + self.arrays[41][1]
        self.m[self.pc_base - BASE:self.pc_base - BASE + self.prof["boxes"] * pc["box_stride"]] = bytes(
            self.prof["boxes"] * pc["box_stride"])
        for (box, slot), mon in self.boxes.items():
            self.put(self.box_addr(box, slot), mon.box_raw())

    def box_addr(self, box, slot):
        pc = self.prof["pc"]
        return self.pc_base + pc["box_base"] + box * pc["box_stride"] + slot * pc["mon_stride"]

    # ── the saved party / boxes, as the codec reads them (independent of the Lua reads) ─────
    def saved_party(self):
        count = self.r(self.party_base + 4, 4)
        return [codec.decrypt_party(self.get(self.party_base + 8 + 0xEC * i, codec.PARTY_MON_SIZE))
                for i in range(count)]

    extra_off = 8 + 6 * 0xEC                                # PartyCore: max, count, mons[6]; then PartyExtra

    def saved_extra(self, slot):
        return self.get(self.party_base + self.extra_off + 5 * slot, 5)

    def saved_hp(self, slot):
        return struct.unpack_from("<H", self.saved_party()[slot], 0x8E)[0]

    def saved_keys(self):
        return [key_of(struct.unpack_from("<I", p, 0)[0], struct.unpack_from("<I", p, 12)[0]) for p in self.saved_party()]

    def box_keys(self):
        out = {}
        for box in range(self.prof["boxes"]):
            for slot in range(self.prof["mons_per_box"]):
                raw = self.get(self.box_addr(box, slot), codec.BOX_MON_SIZE)
                if not any(raw):
                    continue
                try:
                    plain = codec.decrypt_box(raw)
                except codec.Gen4CodecError:
                    continue
                if struct.unpack_from("<H", plain, 8)[0] == 0:
                    continue
                out[key_of(struct.unpack_from("<I", plain, 0)[0], struct.unpack_from("<I", plain, 12)[0])] = (box, slot)
        return out

    def set_badges(self, johto, kanto):
        tr = self.prof["trainer"]
        base = self.dyn + self.arrays[1][1] + tr["profile_off_in_array"]
        self.m[base + tr["johto_badges_off"] - BASE] = johto
        self.m[base + tr["kanto_badges_off"] - BASE] = kanto

    def modified_word_addr(self):
        return self.pc_base + self.prof["pc"]["box_modified_flag_off"]

    # ── field chain ─────────────────────────────────────────────────────────────────
    def set_overlay(self, ovy, slot=0, active=1):
        t = self.title["overlay_table"]
        self.w(t["address"] + slot * t["entry_size"] + t["id_off"], ovy)
        self.w(t["address"] + slot * t["entry_size"] + t["active_off"], active)

    def field(self, *, live=1, task=0, app=APP, launched=0, driver_state=1, paused=0):
        pf = self.prof["probe_field"]
        self.w(FS + pf["live"], live)
        self.w(FS + pf["task"], task)
        self.w(SUB + pf["field_app"], app)
        self.w(SUB + pf["launched_app"], launched)
        self.w(SUB + pf["paused"], paused)
        self.m[DRV_DATA + pf["save_state"] - BASE] = driver_state

    # ── battle ──────────────────────────────────────────────────────────────────────
    def enter_battle(self, *, btype=0, cmd=5, local=((0, 0),), outcome=0):
        """Launch the battle app: `local` = ((battler, party_slot), ...); the foe is battler 1 (3)."""
        b = self.prof["battle"]
        self.field(launched=MAN)
        w = self.w
        w(MAN + b["template_off"], b["template_id"])
        w(MAN + b["man_data_off"], BS)
        w(BS + b["ctx_off"], CTX)
        w(BS + b["type_off"], btype)
        self.m[BS + b["outcome_off"] - BASE] = outcome
        w(BS + 0x68, P0)
        w(BS + 0x6C, P1)
        self.btype, self.in_battle = btype, True
        for base, mons in ((P0, self.party), (P1, [self.foe])):
            w(base, 6)
            w(base + 4, len(mons))
            for i, mon in enumerate(mons):
                self.put(base + 8 + 0xEC * i, mon.party_raw())
        w(CTX + 8, cmd)
        for bt in range(b["max_battlers"]):
            self.m[CTX + b["selected_off"] + bt - BASE] = 6
        for bt, slot in local:
            self.battler(bt, self.party[slot], slot)
        self.battler(1, self.foe, 0)
        w(CTX + b["fainted_flag_off"], 0)

    def battler(self, bt, mon, slot):
        b = self.prof["battle"]
        a = CTX + b["mons_off"] + b["mon_size"] * bt
        self.m[CTX + b["selected_off"] + bt - BASE] = slot
        self.w(a + b["species_off"], mon.species, 2)
        self.m[a + b["level_off"] - BASE] = mon.level
        self.w(a + b["hp_off"], mon.hp)
        self.w(a + b["max_hp_off"], mon.max_hp, 2)
        self.w(a + b["personality_off"], mon.pid)
        self.w(a + b["otid_off"], mon.otid)

    def battler_addr(self, bt, field):
        b = self.prof["battle"]
        return CTX + b["mons_off"] + b["mon_size"] * bt + b[field]

    def set_battle_hp(self, bt, hp):
        self.w(self.battler_addr(bt, "hp_off"), hp)

    def set_cmd(self, cmd):
        self.w(CTX + 8, cmd)

    def set_outcome(self, v):
        self.m[BS + self.prof["battle"]["outcome_off"] - BASE] = v

    def set_repl(self, bt, v=1):
        self.w(CTX + 0x13C + 4 * bt, v)

    def leave_battle(self):
        self.field(launched=0)
        self.in_battle = False

    def battle_party_rec(self, slot):
        return P0 + 8 + 0xEC * slot

    def battle_party_hp(self, slot):
        rec = self.battle_party_rec(slot)
        plain = codec.decrypt_party(self.get(rec, codec.PARTY_MON_SIZE))
        return struct.unpack_from("<H", plain, 0x8E)[0]

    def battler_hp(self, bt):
        v = self.r(self.battler_addr(bt, "hp_off"), 4)
        return v - (1 << 32) if v >= 1 << 31 else v

    def faint_bit(self, bt):
        return (self.r(CTX + self.prof["battle"]["fainted_flag_off"], 4) >> (24 + bt)) & 1

    # ── the fake BizHawk ────────────────────────────────────────────────────────────
    def _make_io(self):
        def rd(n):
            def f(a, domain=None):
                self.reads += 1
                if self.read_log is not None:
                    self.read_log.append(a)
                if a < BASE or a + n > BASE + SIZE:
                    return None
                return int.from_bytes(self.m[a - BASE:a - BASE + n], "little")
            return f

        def read_range(a, n, domain=None):
            self.reads += 1
            return self.lua.table_from(list(self.m[a - BASE:a - BASE + n]))

        def wr(n):
            def f(a, v):
                self.writes.append((self.frame, a, n))
                if a in self.drop_writes:
                    return
                self.w(a, v, n)
            return f

        def on_bus_exec(fn, addr, name, domain):
            self.serial += 1
            self.hook_registrations += 1
            handle = f"{{h-{self.serial}}}"
            self.hooks[handle] = (fn, addr, name)
            return handle

        def unregister(handle):
            return self.hooks.pop(handle, None) is not None

        return self.lua.table_from({
            "read_u8": rd(1), "read_u16": rd(2), "read_u32": rd(4), "read_range": read_range,
            "write_u8": wr(1), "write_u16": wr(2), "write_u32": wr(4),
            "framecount": lambda: self.frame, "register": lambda name: self.regs.get(name, 0),
            "on_bus_exec": on_bus_exec, "unregister": unregister,
        })

    def _make_net(self):
        def send(line):
            msg = json.loads(line)
            problems = [x for x in ps.validate_event(msg, strict=True)
                        if "'writes_enabled'" not in x]         # the core stamps it on every hello
            if self.title_name == "heartgold_hge":            # the server does not route the hge rom_type yet
                problems = [p for p in problems if "not one the server routes" not in p]
            assert not problems, f"{msg}: {problems}"
            self.sent.append(msg)
            self.sent_frames.append(self.frame)

        def receive():
            return self.replies.pop(0) if self.replies else None

        return self.lua.table_from({"connected": lambda: self.connected, "pump": lambda: None, "send": send,
                                    "receive": receive})

    def _make_hud(self):
        t = self.lua.table()
        for name in ("show", "prompt", "set_game_over", "set_rebuilding", "clear_rebuilding"):
            t[name] = (lambda n: lambda *a: self.hud.append((n, *a)))(name)
        return t

    # ── driving ─────────────────────────────────────────────────────────────────────
    def dispatch(self, addr, r0=None, r1=None):
        """The game runs the function at `addr` during the NEXT frame (r0/r1 as the ARM9 registers)."""
        self.pending_dispatch.append((addr, r0, r1))

    def dispatch_seam(self, *, r0=BS, r1=CTX, cmd=None):
        """The D7 seam: set ctx.command and run the seam function (address from the live site)."""
        seam = self.seam_addr()
        if cmd is not None:
            self.set_cmd(cmd)
        self.dispatch(seam, r0, r1)

    def seam_addr(self):
        d7 = (self.d7 or self.prof["battle"]["d7"])["seam"]
        if "addr" in d7:
            return d7["addr"]
        return self.r(d7["table"] + 4 * d7["cmd"], 4) & ~1

    def _fire(self):
        for addr, r0, r1 in self.pending_dispatch:
            self.regs["ARM9 r0"], self.regs["ARM9 r1"], self.regs["ARM9 r15"] = r0 or 0, r1 or 0, addr + 4
            for fn, a, _ in list(self.hooks.values()):
                if a == addr:
                    fn(addr, self.r(addr, 4), 0)
        self.pending_dispatch = []

    def advance(self, n=1):
        for _ in range(n):
            self.w(self.sys, self.r(self.sys, 4) + 1)
            if self.order == "hook_old":
                self._fire()
                self.frame += 1
            else:
                self.frame += 1
                self._fire()
            self.session.frame_end(self.session)

    def run_to(self, frame):
        self.advance(frame - self.frame)

    def boot(self, frames=75):
        """Past the 60-frame validation (writes ENABLED), the hello, and the first idle frames."""
        self.advance(frames)

    def reply(self, *commands):
        self.replies.append(json.dumps({"commands": list(commands)}))

    # ── observation ─────────────────────────────────────────────────────────────────
    def events(self, name):
        return [m for m in self.sent if m["event"] == name]

    @property
    def state(self):
        return self.session.state

    @property
    def signals(self):
        return self.session.signals
