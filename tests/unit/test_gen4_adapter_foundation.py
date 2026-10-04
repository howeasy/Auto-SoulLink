"""Per-foundation facts for the ONE Gen 4 adapter (`gen4_hgsspt`).

HeartGold, SoulSilver and hg-engine share a class, a game_id and an import, and they do not
share a cartridge: hg-engine stores 30 PC boxes where HeartGold stores 18. Two properties here
used to answer for HeartGold without ever being asked which foundation they were speaking for.

  memorial_box_index  a bare 17, commented "last of 18 boxes". On hg-engine that names a box
                      twelve past the end of storage, so a burial overflowed into boxes the
                      cartridge does not have.
  status_token        inherited the base "", so every Gen 4 party row has rendered with no
                      status at all even though the client has been sending `status_cond`
                      since it began sending party entries.

Every test names the source it is pinned against. A number that happens to be right for one
cartridge is not evidence for the next one, which is how 17 survived as long as it did.
"""

import json
import os
from dataclasses import replace

import pytest

from server.adapters import foundation_for_rom_type, gen4_codec, gen4_hgsspt as gen4
from server.adapters.gen4_hgsspt import Gen4Adapter

_PACK_DIR = os.path.dirname(gen4._HGSS_PACK_DIR)          # .../data/games
_ROUTED = (("heartgold", "gen4_hgss", "hgss", "heartgold"),
           ("soulsilver", "gen4_hgss", "hgss", "soulsilver"),
           ("heartgold_hge", "gen4_hge", "hge", "heartgold_hge"))


def _pack_geometry(pack: str, title: str) -> tuple[int, int, int]:
    """(boxes, memorial_box, mons_per_box) as the CLIENT's own pack states them.

    data/games/gen4_hgss/profile.json holds HeartGold and SoulSilver (titles.heartgold:3563,
    :3641-3642 and titles.soulsilver:9347, :9425-9426); data/games/gen4_hge/profile.json holds
    the hg-engine fork (titles.heartgold_hge:3805, :3884-3885, evidence include/constants/
    save.h:26 NUM_PC_BOXES 30). This is the layout the Lua client reads for its own box maths,
    so it is the half of the question the server must agree with.
    """
    with open(os.path.join(_PACK_DIR, pack, "profile.json"), encoding="utf-8") as fh:
        entry = json.load(fh)["titles"][title]["profile"]
    return entry["boxes"], entry["memorial_box"], entry["mons_per_box"]


# ── the memorial box is the cartridge's own ───────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type,memorial", [("heartgold", 17), ("soulsilver", 17),
                                              ("heartgold_hge", 29)])
def test_the_memorial_box_index_is_the_cartridges_own(rom_type, memorial):
    a = Gen4Adapter(rom_type=rom_type)
    assert a.memorial_box_index == memorial
    assert a.mons_per_box == 30


@pytest.mark.parametrize("rom_type,pack,profile,title", _ROUTED)
def test_the_adapter_agrees_with_the_pack_the_client_reads(rom_type, pack, profile, title):
    """The server's answer and the client's own box maths must not disagree.

    hg-engine's 29 is not a policy choice: its storage is 30 boxes wide (cur_box_off 0x1E000 in
    gen4_codec.PROFILES["hge"]), so box 17 would be an ordinary PC box two-thirds of the way
    down, not the burial box — and the census `/api/debug/raw_state` counts would move with it.
    """
    boxes, memorial, mons = _pack_geometry(pack, title)
    a = Gen4Adapter(rom_type=rom_type)
    assert (a.memorial_box_index, a.mons_per_box) == (memorial, mons)
    assert a.memorial_box_index == boxes - 1
    assert gen4_codec.PROFILES[profile].box_count == boxes


@pytest.mark.parametrize("rom_type,foundation", [("heartgold", "gen4_hgss"),
                                                 ("soulsilver", "gen4_hgss"),
                                                 ("heartgold_hge", "gen4_hge")])
def test_the_foundation_is_the_registrys_answer_not_a_local_table(rom_type, foundation):
    """One place decides what a rom_type IS; the adapter asks it rather than re-deciding."""
    assert Gen4Adapter(rom_type=rom_type)._foundation == foundation_for_rom_type(rom_type)
    assert foundation_for_rom_type(rom_type) == foundation


def test_an_hge_box_count_of_18_would_move_the_answer_back_to_17(monkeypatch):
    """The control for the derivation: the value follows gen4_codec, it is not written down.

    A hardcoded `return 29`, or a local {foundation: index} table, passes every other test here
    and fails this one. So does the `return 17` this replaced.
    """
    monkeypatch.setitem(gen4_codec.PROFILES, "hge",
                        replace(gen4_codec.PROFILES["hge"], box_count=18))
    assert Gen4Adapter(rom_type="heartgold_hge").memorial_box_index == 17


def test_an_unrouted_rom_type_gets_no_memorial_box_at_all():
    """Platinum is refused by the registry, so there is no layout to answer with.

    Answering 17 anyway would keep the old wrong answer alive for exactly the cartridge it was
    wrong for; -1 is the base contract's "no dedicated memorial box".
    """
    assert foundation_for_rom_type("platinum") is None
    assert foundation_for_rom_type("renegade_platinum") is None
    a = Gen4Adapter(rom_type="platinum")
    assert a.memorial_box_index == -1
    assert a.mons_per_box == 0


def test_the_board_counts_the_memorial_box_of_the_cartridge_it_is_serving(tmp_path):
    """server.py:5117 — the census count, through the adapter, for hg-engine and for a refusal."""
    from server.server import SLinkServer

    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.adapter = srv.adapter = Gen4Adapter(rom_type="heartgold_hge")
    assert srv._memorial_box_indices("a") == {29}
    srv.adapter = srv.state.adapter = Gen4Adapter(rom_type="heartgold")
    assert srv._memorial_box_indices("a") == {17}
    srv.adapter = srv.state.adapter = Gen4Adapter(rom_type="platinum")
    assert srv._memorial_box_indices("a") == set()


# ── the status word ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status_cond,token", [
    (0x000, ""),      # STATUS_NONE (battle.h:296)
    (0x001, "SLP"),    # STATUS_SLEEP_0 (battle.h:297)
    (0x002, "SLP"),    # STATUS_SLEEP_1 — a COUNTER, so turn 2 is asleep too
    (0x007, "SLP"),    # STATUS_SLEEP (battle.h:307)
    (0x008, "PSN"),    # STATUS_POISON (battle.h:300)
    (0x010, "BRN"),    # STATUS_BURN (battle.h:301)
    (0x020, "FRZ"),    # STATUS_FREEZE (battle.h:302)
    (0x040, "PAR"),    # STATUS_PARALYSIS (battle.h:303)
    (0x080, "TOX"),    # STATUS_BAD_POISON (battle.h:304)
    (0x088, "TOX"),    # bad poison also sets poison: TOX must win, or a badly poisoned mon reads PSN
    (0x208, "PSN"),    # poison + STATUS_POISON_COUNT 2 (battle.h:305, bits 8-11)
    (0x288, "TOX"),    # ... and the same word with bad poison
    (0x200, ""),       # a poison counter on its own is not a condition
    (0x8000, ""),      # nothing above bit 7 is one either
])
def test_status_token_decodes_the_word_the_client_sends(status_cond, token):
    assert Gen4Adapter(rom_type="heartgold").status_token(status_cond) == token


@pytest.mark.parametrize("rom_type", ["heartgold", "soulsilver", "heartgold_hge"])
def test_the_token_is_the_same_word_on_every_gen4_foundation(rom_type):
    """The status layout is one cartridge-wide format, unlike the box geometry."""
    a = Gen4Adapter(rom_type=rom_type)
    assert [a.status_token(w) for w in (0x00, 0x02, 0x08, 0x88)] == ["", "SLP", "PSN", "TOX"]


def test_a_gen4_party_row_now_shows_its_status(tmp_path):
    """The server path that renders it: `_build_link_panel` -> adapter.status_token.

    server.py:1901 puts the token in field 7 of the row. Before this adapter had the method,
    Gen 4 rows ended with an empty field however badly poisoned the mon was.
    """
    from server.server import SLinkServer
    from server.state import LinkEntry, LinkStatus, MonInfo

    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.adapter = srv.adapter = Gen4Adapter(rom_type="heartgold")
    srv.state.links = [LinkEntry(area_id="route_1",
                                 a=MonInfo(key="aaa", level=12, species=25, nickname="Sparky"),
                                 b=MonInfo(key="bbb", level=11, species=27, nickname="Ratty"),
                                 status=LinkStatus.ALIVE)]
    detail = {"level": 12, "hp": 19, "maxHP": 23, "nickname": "Sparky", "status_cond": 0x08}
    srv.party_details["a"] = {"aaa": detail}

    def token() -> str:
        return srv._build_link_panel("a")["rows"][0].split("|")[6]

    assert token() == "PSN"
    detail["status_cond"] = 0x88          # badly poisoned: TOX, not PSN
    assert token() == "TOX"
    detail["status_cond"] = 0
    assert token() == ""
    detail["status_cond"] = 0x40          # paralysed
    assert token() == "PAR"


# ── party_blob_size: OPEN, left at 0 on purpose ──────────────────────────────────────────────

def test_a_gen4_party_snapshot_caches_no_blobs_because_the_client_sends_none():
    """OPEN. `party_blob_size` stays 0 and this test says why, so it is a decision not a gap.

    The size would be the party record's 0xEC (gen4_codec.PARTY_MON_SIZE), but no Gen 4 client
    has ever sent `blob_hex`: lua/gen4/client.lua:316-319 lists it among the fields it does NOT
    supply and party_wire (:322-335) emits no such key (conformance map item 9, na). A non-zero
    size would NOT make the server require blobs — `_ingest_party_blobs` drops an entry whose
    blob_hex is absent or the wrong length (state.py:4444) and the only consumer, the Rival Team
    Swap, is already dead for Gen 4 because `rival_trainer_ids()` is the empty base default
    (base.py:210-224). So returning 0xEC today changes nothing at runtime and would advertise a
    blob contract no Gen 4 receipt backs. It flips when a client sends one.
    """
    from server.state import SoulLinkState

    st = SoulLinkState(adapter=Gen4Adapter(rom_type="heartgold"))
    st._ingest_party_blobs("a", [{"slot": 0, "key": "AAAABBBB:11223344", "species_id": 25,
                                  "blob_hex": "AB" * gen4_codec.PARTY_MON_SIZE}])
    assert st.partner_blobs["a"] == []
