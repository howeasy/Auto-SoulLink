"""Saved trade delta MODEL: protected bytes survive valid checksum rewrites."""
import pytest

from server.adapters import gen2_codec as codec
from tools import gen2_trade_save_delta as delta


def test_delta_helper_exists():
    assert callable(delta.verify_trade_saved_delta)


@pytest.fixture(scope="module", params=["crystal", "gold", "silver"])
def case(request):
    title = request.param
    layout = codec.for_foundation(title)
    before = (delta.ROOT / f"tests/fixtures/gen2/{title}_battle.SaveRAM").read_bytes()
    mons = codec.decode_saved_party(before[:32768], layout, copy_name="primary")["mons"]
    party = [{"species_marker": m["species_marker"], "blob_hex": codec.encode_party_blob(m, layout).hex()} for m in mons]
    own = {"slot": 0, **party[0]}
    incoming = bytearray(bytes.fromhex(party[0]["blob_hex"]))
    incoming[6] ^= 1  # independently distinct incoming OT
    partner = {"species_marker": party[0]["species_marker"], "blob_hex": incoming.hex()}
    incoming[27] = 70
    expected_party = party[1:] + [{"species_marker": partner["species_marker"], "blob_hex": incoming.hex()}]
    dex = {copy: {kind + "_hex": before[delta._offset(layout, symbol, 32, copy):delta._offset(layout, symbol, 32, copy) + 32].hex()
                 for kind, symbol in (("caught", "wPokedexCaught"), ("seen", "wPokedexSeen"))}
           for copy in ("primary", "backup")}
    kwargs = {"title": title, "expected_party": expected_party, "expected_dex": dex, "partner_offer": partner,
              "own_offer": own, "partner_player_name": b"\x80" + b"\x50" * 10}
    after = delta._expected(before, layout, expected_party, dex, partner, own, kwargs["partner_player_name"])
    return layout, before, after, kwargs


@pytest.fixture(autouse=True)
def reuse_verified_layout(monkeypatch, case):
    layout = case[0]
    monkeypatch.setattr(codec, "for_foundation", lambda title, root=delta.ROOT: layout)


def checksums(raw, layout):
    out = bytearray(raw)
    for copy, offset in layout.checksum_offsets.items():
        out[offset:offset + 2] = codec.sav_checksum(bytes(out[:32768]), layout, copy).to_bytes(2, "little")
    return bytes(out)


def test_native_delta_and_only_documented_scratch(case):
    layout, before, after, kwargs = case
    delta.verify_trade_saved_delta(before, after, **kwargs)
    changed = bytearray(after)
    changed[0] ^= 1
    changed[-1] ^= 1  # RTC tail is outside CartRAM.
    if layout.title != "crystal":
        changed[0x1800] ^= 1
    delta.verify_trade_saved_delta(before, bytes(changed), **kwargs)
    # Sender name, frozen slot 1 and incoming slot 0 have exact byte meaning.
    if layout.title != "crystal":
        start = delta._offset(layout, "wOTPartyMon1", 96, "primary")
        assert after[start:start + 48].hex() == kwargs["partner_offer"]["blob_hex"][:96]
        assert after[start + 48:start + 96].hex() == kwargs["own_offer"]["blob_hex"][:96]


@pytest.mark.parametrize("symbol", ["wMoney", "wItems", "wEventFlags", "wDayCareMan", "wUnownDex", "wRoamMon1"])
def test_rechecksummed_unrelated_saved_bytes_refused(case, symbol):
    layout, before, after, kwargs = case
    changed = bytearray(after)
    for copy in ("primary", "backup"):
        changed[delta._offset(layout, symbol, 1, copy)] ^= 1
    changed = checksums(changed, layout)
    assert codec.strict_checksum_witness(changed[:32768], layout)["valid"]
    with pytest.raises(RuntimeError, match="unexpected saved byte"):
        delta.verify_trade_saved_delta(before, changed, **kwargs)


@pytest.mark.parametrize("symbol", ["sBox1", "sMailboxCount", "sPartyMailBackup", "sRTCStatusFlags", "sStackTop"])
def test_unchecksummed_protected_sram_refused(case, symbol):
    layout, before, after, kwargs = case
    changed = bytearray(after)
    changed[delta._flat(layout, symbol)] ^= 1
    with pytest.raises(RuntimeError, match="unexpected saved byte"):
        delta.verify_trade_saved_delta(before, checksums(changed, layout), **kwargs)


def test_gs_unauthenticated_sender_or_extra_staging_refused(case):
    layout, before, after, kwargs = case
    if layout.title == "crystal":
        return
    with pytest.raises(RuntimeError, match="authenticated staged"):
        delta.verify_trade_saved_delta(before, after, **{**kwargs, "partner_player_name": None})
    changed = bytearray(after)
    for copy in ("primary", "backup"):
        changed[delta._offset(layout, "wOTPartyMon3", 1, copy)] ^= 1
    with pytest.raises(RuntimeError, match="unexpected saved byte"):
        delta.verify_trade_saved_delta(before, checksums(changed, layout), **kwargs)


def test_sender_encoder_uses_glyphs_not_raw_padding_or_uppercase(case):
    title = case[0].title
    fallback = b"\x82" + b"\x50" * 10
    assert delta.encode_partner_name(title, "Aa\n😀", fallback) == b"\x80\xa0" + b"\x50" * 9
    assert delta.encode_partner_name(title, "\n😀", fallback) == fallback
    assert delta.encode_partner_name(title, "A" * 12, fallback) == b"\x80" * 10 + b"\x50"


def test_mail_compaction_and_backup_are_exact(case):
    layout, before, _, kwargs = case
    mail = delta._flat(layout, "sPartyMail")
    backup = delta._flat(layout, "sPartyMailBackup")
    stride = (backup - mail) // 6
    raw = bytearray(before)
    for slot in range(6):
        raw[mail + slot * stride:mail + (slot + 1) * stride] = bytes([slot + 1]) * stride
    before = bytes(raw)
    after = delta._expected(before, layout, kwargs["expected_party"], kwargs["expected_dex"],
                            kwargs["partner_offer"], kwargs["own_offer"], kwargs["partner_player_name"])
    count = len(kwargs["expected_party"])
    expected_mail = b"".join(bytes([i + 2 if i < count - 1 else i + 1]) * stride for i in range(6))
    assert after[mail:mail + 6 * stride] == expected_mail
    assert after[backup:backup + 6 * stride] == expected_mail
    delta.verify_trade_saved_delta(before, after, **kwargs)


def test_capacity_tail_shifts_without_broad_unused_slot_exemption(case):
    layout, before, _, kwargs = case
    raw = bytearray(before)
    for copy in ("primary", "backup"):
        for name, stride in (("wPartyMon1", 48), ("wPartyMonOTs", 11), ("wPartyMonNicknames", 11)):
            start = delta._offset(layout, name, 6 * stride, copy)
            for i in range(1, 6):
                raw[start + i * stride:start + (i + 1) * stride] = bytes([0x60 + i]) * stride
    before = checksums(raw, layout)
    after = delta._expected(before, layout, kwargs["expected_party"], kwargs["expected_dex"],
                            kwargs["partner_offer"], kwargs["own_offer"], kwargs["partner_player_name"])
    for copy in ("primary", "backup"):
        for name, stride in (("wPartyMon1", 48), ("wPartyMonOTs", 11), ("wPartyMonNicknames", 11)):
            start = delta._offset(layout, name, 6 * stride, copy)
            # Count-one fixtures append to slot0 after full-capacity removal.
            assert after[start + stride:start + 5 * stride] == b"".join(bytes([0x60 + i]) * stride for i in range(2, 6))
            assert after[start + 5 * stride:start + 6 * stride] == bytes([0x65]) * stride
    delta.verify_trade_saved_delta(before, after, **kwargs)
    changed = bytearray(after)
    for copy in ("primary", "backup"):
        changed[delta._offset(layout, "wPartyMon6", 1, copy)] ^= 1
    with pytest.raises(RuntimeError, match="unexpected saved byte"):
        delta.verify_trade_saved_delta(before, checksums(changed, layout), **kwargs)
