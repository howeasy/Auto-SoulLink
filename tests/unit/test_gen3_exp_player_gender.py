"""EXP-PLAYER-GENDER: the expansion profile carries SaveBlock2.playerGender so the client reports
player_gender and the rival-by-gender trainer panel filter (server.py, gated on the player's known
gender) is live on gen3_exp, not dead.

Offset sources, all agreeing: the compiler probe (data/games/gen3_exp/28877d73/harness_facts.json,
tools/expansion_harness_offsets.c F(SaveBlock2, playerGender)), the pinned struct
(e8bd1cd7 include/global.h:591 `/*0x08*/ u8 playerGender; // MALE, FEMALE`) and the reference ROM
(ScrCmd_checkplayergender 0x081f9dc0: `ldrb r2, [r2, #8]` off gSaveBlock2Ptr 0x030051c0 into
gSpecialVar_Result 0x0200156e).
"""
import json
import os
from pathlib import Path

import lupa
import pytest

from server.adapters.gen3_expansion import Gen3ExpansionAdapter
from server.server import SLinkServer
from tests.unit.gen3_world import SB2_ADDR
from tools import gen_gen3_profile as profile

PACK = profile.REPO / "data/games/gen3_exp/28877d73"
TITLE = profile.EXPANSION_TITLE
OFFSET = 0x08


def _title():
    return json.loads((PACK / "profile.json").read_text(encoding="utf-8"))["titles"][TITLE]


def test_profile_pins_player_gender_to_the_compiler_fact():
    harness = json.loads((PACK / "harness_facts.json").read_text(encoding="utf-8"))
    compiled = harness["structs"]["SaveBlock2"]["fields"]["playerGender"]
    assert compiled == {"offset": OFFSET, "size": 1}
    title = _title()
    assert title["derived"]["SB2_PLAYER_GENDER_OFFSET"] == OFFSET
    assert "playerGender" in title["_src"]["derived.SB2_PLAYER_GENDER_OFFSET"]


def test_rom_reads_player_gender_at_that_offset():
    capstone = pytest.importorskip("capstone")
    artifacts = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", profile.REPO / ".cache/expansion-output/reference"))
    names = ("pokeemerald.gba", "pokeemerald.sym")
    if not all((artifacts / n).is_file() for n in names):
        pytest.skip(f"local copyrighted ROMs absent: {artifacts}")
    context = profile.expansion_inputs(artifacts=artifacts)
    fn = profile.expansion_symbol(context, "ScrCmd_checkplayergender")
    ptr = profile.expansion_symbol(context, "gSaveBlock2Ptr")["address"]
    result = profile.expansion_symbol(context, "gSpecialVar_Result")["address"]
    base = fn["address"] - 0x08000000
    code = context["rom"][base:base + fn["size"]]
    ops = list(capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB).disasm(code, fn["address"]))
    assert [i.mnemonic for i in ops[:4]] == ["ldr", "ldr", "ldr", "ldrb"]
    assert ops[3].op_str == f"r2, [r2, #{OFFSET}]"
    # both literal-pool words after the code: &gSaveBlock2Ptr and &gSpecialVar_Result
    pool = [int.from_bytes(code[i:i + 4], "little") for i in range(len(code) - 8, len(code) - 3, 4)]
    assert pool == [ptr, result]


def _native_trainer(gender):
    """lua/gen3/reads.lua (the client's read_trainer, which hello/tick forward verbatim:
    lua/gen3/client.lua:1200,1237) over the REAL expansion profile and checkpoint pointers,
    with a fake bus holding a SaveBlock2 whose playerGender byte is `gender`."""
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    json_codec = L.eval(f'dofile("{(profile.REPO / "lua/json_codec.lua").as_posix()}")')
    reads = L.eval(f'dofile("{(profile.REPO / "lua/gen3/reads.lua").as_posix()}")')
    prof = json_codec.decode((PACK / "profile.json").read_text(encoding="utf-8"))["titles"][TITLE]
    checkpoint = json_codec.decode((PACK / "write_checkpoint.json").read_text(encoding="utf-8"))[TITLE]
    ptr_addr = checkpoint["pointers"]["gSaveBlock2Ptr"]["address"]
    mem = {ptr_addr + i: b for i, b in enumerate(SB2_ADDR.to_bytes(4, "little"))}
    mem[SB2_ADDR + OFFSET] = gender
    rd = lambda n: (lambda a: sum(mem.get(int(a) + i, 0) << 8 * i for i in range(n)))
    io = L.table(read_u8=rd(1), read_u16=rd(2), read_u32=rd(4),
                 read_bytes=lambda a, n: L.table(*[mem.get(int(a) + i, 0xFF) for i in range(int(n))]))
    return reads.new(prof, io, checkpoint["pointers"]).read_trainer()


@pytest.mark.parametrize("gender", [0, 1])
def test_expansion_client_reads_the_native_player_gender(gender):
    assert _native_trainer(gender).player_gender == gender


def test_an_out_of_range_gender_byte_is_absent():
    assert _native_trainer(2).player_gender is None


@pytest.mark.parametrize("gender,shown,hidden", [(0, "May", "Brendan"), (1, "Brendan", "May")])
def test_rival_panel_follows_the_client_read_gender(gender, shown, hidden):
    """Profile offset -> client read -> server.player_gender -> panel: the whole chain."""
    srv = SLinkServer.__new__(SLinkServer)
    srv.adapter = Gen3ExpansionAdapter()
    srv._player_adapters = {}
    srv.player_gender = {"a": _native_trainer(gender).player_gender}
    html = srv._trainer_panel_html("route_103", "a")
    assert shown in html and hidden not in html
