"""RR-DURABLE [ROM] facts behind the companion's durable-trade hooks (Codex Emerald ruling P2:
never inherit RR save internals from FR address equality alone). Every engine entry the
handlers.c hooks call must be byte-identical to FireRed's in the RR ROM, RR's save must
serialize through the CFRU 0xFF0 table the reload proof reads, and every RAM word the hooks read
must be loaded by (at least 80% of) the same literal pools as in FireRed."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROMS = Path(os.environ.get("SLINK_GEN3_ROMS", ROOT))
BASE = 0x08000000


@pytest.fixture(scope="module")
def roms():
    fr, rr = ROMS / "Pokemon - FireRed Version (USA).gba", ROMS / "Pokemon - Radical Red.gba"
    if not fr.exists() or not rr.exists():
        pytest.skip("FR/RR base ROMs absent (SLINK_GEN3_ROMS)")
    return fr.read_bytes(), rr.read_bytes()


def fr_symbols():
    out = {}
    for line in (ROOT / "data/gen3/pret/pokefirered.sym").read_text().splitlines():
        row = line.split()
        if len(row) == 4:
            out[row[3]] = (int(row[0], 16), int(row[2], 16))
    return out


def handlers_define(name):
    src = (ROOT / "patch/src/handlers.c").read_text(encoding="utf-8")
    m = re.search(rf"^#define\s+{name}\s+.*?(0x[0-9A-Fa-f]+)u", src, re.M)
    assert m, name
    return int(m[1], 16)


# handlers.c durable hook -> the pret FR function it calls (Thumb entry = address | 1)
HOOK_FUNCTIONS = {
    "Field_AskSaveTheGame": "Field_AskSaveTheGame", "SaveMapView": "SaveMapView",
    "SaveQuestLogData": "SaveQuestLogData", "TrySavingData": "TrySavingData",
    "ItemIsMail": "ItemIsMail", "DO_INGAME_TRADE": "DoInGameTradeScene",
}
# the save dialog the pre-save polls, and the scene/script plumbing it runs through
IDENTICAL = ("task50_save_game", "SaveDialogCB_PrintAskSaveText", "SaveDialogCB_AskSaveHandleInput",
             "SaveDialogCB_PrintSavingDontTurnOffPower", "SaveDialogCB_DoSave",
             "SaveDialogCB_PrintSaveResult", "SaveDialogCB_ReturnSuccess", "SaveDialogCB_ReturnError",
             "ScriptContext_SetupScript", "TradeMons")


def test_every_hook_entry_is_frs_function_byte_for_byte(roms):
    fr, rr = roms
    sym = fr_symbols()
    for define, name in HOOK_FUNCTIONS.items():
        address, size = sym[name]
        assert handlers_define(define) & ~1 == address, define
        assert rr[address - BASE:address - BASE + size] == fr[address - BASE:address - BASE + size], name
    for name in IDENTICAL:
        address, size = sym[name]
        assert rr[address - BASE:address - BASE + size] == fr[address - BASE:address - BASE + size], name


def test_rr_save_serializes_through_cfru_bodies_and_the_0xff0_table(roms):
    """TrySavingData (=FR) calls HandleSavingData, whose RR entry is `ldr r1,=0x090B8E09; bx r1`
    (CFRU body); HandleWriteSector's is `ldr r2,=0x090B8CB5; bx r2`; UpdateSaveAddresses' pool
    word points at CFRU's {u16 offset, u16 size} table, which is exactly the 0xFF0 layout."""
    from server.adapters import gen3_codec as C
    _, rr = roms
    sym = fr_symbols()
    word = lambda a: int.from_bytes(rr[a - BASE:a - BASE + 4], "little")  # noqa: E731
    handle_saving, write_sector = sym["HandleSavingData"][0], sym["HandleWriteSector"][0]
    assert rr[handle_saving - BASE:handle_saving - BASE + 4] == bytes.fromhex("00490847")
    assert word(handle_saving + 4) == 0x090B8E09
    assert rr[write_sector - BASE:write_sector - BASE + 4] == bytes.fromhex("004a1047")
    assert word(write_sector + 4) == 0x090B8CB5
    try_saving = sym["TrySavingData"][0]
    assert rr[try_saving + 0x10 - BASE:try_saving + 0x14 - BASE] == bytes.fromhex("fff768ff")  # bl HandleSavingData
    table = word(0x080DA23C)
    assert sym["UpdateSaveAddresses"][0] < 0x080DA23C < handle_saving and table == 0x09148BF0
    rows = C.slot_layout(C.CHUNK_SIZE_CFRU)
    for row in rows:
        at = table - BASE + 4 * row["id"]
        assert (int.from_bytes(rr[at:at + 2], "little"), int.from_bytes(rr[at + 2:at + 4], "little")) \
            == (row["offset"], row["size"]), row


# every RAM word the durable hooks read (handlers.c names -> pret FR symbol)
RAM_WORDS = {"sGlobalScriptContextStatus": "sGlobalScriptContextStatus",
             "gReceivedRemoteLinkPlayers": "gReceivedRemoteLinkPlayers",
             "gLinkTransferringData": "gLinkTransferringData", "sSaveDialogCB": "sSaveDialogCB",
             "sScriptContext2Enabled": "sLockFieldControls", "gSpecialVar_Result": "gSpecialVar_Result",
             "gPlayerPartyCount": "gPlayerPartyCount", "gPlayerParty": "gPlayerParty",
             "gEnemyParty": "gEnemyParty", "gEnemyPartyCount": "gEnemyPartyCount", "gMain": "gMain"}


def test_every_ram_word_is_loaded_by_the_same_rr_literal_pools(roms):
    fr, rr = roms
    sym = fr_symbols()
    for define, name in RAM_WORDS.items():
        address = handlers_define(define)
        assert address == sym[name][0], define
        pat = address.to_bytes(4, "little")
        pools = [i for i in range(0, len(fr) - 3, 4) if fr[i:i + 4] == pat]
        same = sum(rr[i:i + 4] == pat for i in pools)
        # CFRU rewrote a few callers (e.g. 5 of gPlayerPartyCount's 35); the rest are FR's
        assert pools and same * 10 >= len(pools) * 8, (define, same, len(pools))
