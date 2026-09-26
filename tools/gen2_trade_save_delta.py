"""Exact native trade save delta, separate from received-mon projection.

SOURCE: pinned C/G engine/menus/save.asm SaveAfterLinkTrade, move_mon.asm
RemoveMonFromPartyOrBox/AddTempmonToParty, pokemon/mail.asm BackupPartyMonMail,
link/mystery_gift.asm BackupMysteryGift, rtc/rtc.asm SaveRTC. Layout symbols come
from the verified source build. No whole PokemonData or unused-party exemption.
RTC trailer and audited native graphics/window scratch are comparison-only masks.
"""
from pathlib import Path

from server.adapters import gen2_codec as codec
from tools.gen2_duo_oracles import normalized_gameplay_cartram

ROOT = Path(__file__).resolve().parents[1]
REGIONS = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
           "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}


def encode_partner_name(title, text, incoming_ot, *, root=ROOT):
    """Independent transcription of trade_overlay.lua:95-106,152-154.

    Text must come from authenticated server player_identity, not mon OT or an
    unauthenticated receipt. Unsupported/empty text uses the incoming OT bytes.
    No uppercase conversion occurs. Multi-character charmap tokens are not
    consumed as a unit: the production encoder walks Unicode characters.
    """
    from tools.gen2_source_data import load_context
    from tools.gen_gen2_charmap import build, render_lua

    _need(isinstance(incoming_ot, bytes) and len(incoming_ot) == 11, "invalid incoming OT name")
    facts = build(load_context(title, root=Path(root)))
    pack = Path(root) / f"data/games/gen2_{title}/charmap.lua"
    _need(pack.read_text(encoding="utf-8") == render_lua(facts).decode("utf-8"), "receiving charmap differs from pinned source")
    encoding = facts["encoding"]
    glyphs = [encoding[ch] for ch in text if ch in encoding and 0x60 <= encoding[ch] <= 255][:10] if isinstance(text, str) else []
    return bytes(glyphs + [0x50] * (11 - len(glyphs))) if glyphs else incoming_ot


def _need(ok, reason):
    if not ok:
        raise RuntimeError("trade saved delta: " + reason)


def _flat(layout, name):
    return layout.sram_banks[name] * 0x2000 + layout.addresses[name] - 0xA000


def _offset(layout, name, size, copy):
    address = layout.addresses[name]
    for region in layout.regions:
        start = layout.addresses[REGIONS[region.name]]
        if start <= address and address + size <= start + region.length:
            return getattr(region, copy) + address - start
    raise RuntimeError("trade saved delta: symbol outside saved regions: " + name)


def _blob(row):
    _need(isinstance(row, dict), "mon row is not a dict")
    raw = bytes.fromhex(row["blob_hex"])
    _need(len(raw) == 70 and type(row["species_marker"]) is int, "malformed mon row")
    return raw


def _expected(before, layout, expected_party, expected_dex, partner_offer, own_offer, partner_player_name):
    out = bytearray(before)
    party = codec.decode_saved_party(before[:0x8000], layout, copy_name="primary")["mons"]
    count, slot = len(party), own_offer["slot"]
    _need(type(slot) is int and 0 <= slot < count <= 6, "invalid outgoing slot")
    _need(isinstance(expected_party, list) and len(expected_party) == count, "party count changed")
    own, incoming = _blob(own_offer), _blob(partner_offer)
    _need(own == codec.encode_party_blob(party[slot], layout)
          and own_offer["species_marker"] == party[slot]["species_marker"], "outgoing preimage differs")
    _need(partner_offer["species_marker"] != 253, "egg staging marker is not modeled")
    expected_blobs = [_blob(row) for row in expected_party]
    survivors = party[:slot] + party[slot + 1:]
    _need(all(expected_blobs[i] == codec.encode_party_blob(mon, layout)
              and expected_party[i]["species_marker"] == mon["species_marker"]
              for i, mon in enumerate(survivors)), "survivor projection changed")
    if layout.title != "crystal":
        _need(isinstance(partner_player_name, bytes) and len(partner_player_name) == 11,
              "G/S requires authenticated staged partner trainer-name bytes")

    for copy in ("primary", "backup"):
        def put(name, raw, copy=copy):
            start = _offset(layout, name, len(raw), copy)
            out[start:start + len(raw)] = raw

        # Native removal shifts arrays to their capacity ends, not only live rows.
        for name, stride, blob_start in (("wPartyMon1", 48, 0), ("wPartyMonOTs", 11, 48),
                                         ("wPartyMonNicknames", 11, 59)):
            start = _offset(layout, name, 6 * stride, copy)
            if slot < 5:
                out[start + slot * stride:start + 5 * stride] = before[start + (slot + 1) * stride:start + 6 * stride]
            for i, blob in enumerate(expected_blobs):
                out[start + i * stride:start + (i + 1) * stride] = blob[blob_start:blob_start + stride]
        # Shift through the old terminator; append restores count and terminator.
        start = _offset(layout, "wPartySpecies", 7, copy)
        out[start + slot:start + count] = before[start + slot + 1:start + count + 1]
        out[start:start + count + 1] = bytes([r["species_marker"] for r in expected_party] + [255])
        for kind, name in (("caught", "wPokedexCaught"), ("seen", "wPokedexSeen")):
            raw = bytes.fromhex(expected_dex[copy][kind + "_hex"])
            _need(len(raw) == 32, "invalid projected dex")
            put(name, raw)
        if layout.title != "crystal":
            # The current overlay stages only these spans; slot 1 is the held
            # outgoing snapshot. Preserve all other OT scratch, including gaps.
            put("wOTPlayerName", partner_player_name)
            put("wOTPartyCount", b"\x01")
            put("wOTPartySpecies", bytes((incoming[0], 255)))
            for name, stride, blob_start in (("wOTPartyMon1", 48, 0), ("wOTPartyMonOTs", 11, 48),
                                             ("wOTPartyMonNicknames", 11, 59)):
                put(name, incoming[blob_start:blob_start + stride] + own[blob_start:blob_start + stride])

    # Normal Remove (wLinkMode=0) shifts only remaining live mail; tail unchanged.
    mail, backup = _flat(layout, "sPartyMail"), _flat(layout, "sPartyMailBackup")
    stride = _flat(layout, "sPartyMon2Mail") - mail
    _need(stride > 0 and backup - mail == 6 * stride, "unexpected native mail geometry")
    out[mail + slot * stride:mail + (count - 1) * stride] = before[mail + (slot + 1) * stride:mail + count * stride]
    out[backup:backup + 6 * stride] = out[mail:mail + 6 * stride]
    mailbox, mailbox_backup = _flat(layout, "sMailboxCount"), _flat(layout, "sMailboxCountBackup")
    size = mailbox_backup - mailbox
    _need(size == 1 + 10 * stride, "unexpected mailbox geometry")
    out[mailbox_backup:mailbox_backup + size] = out[mailbox:mailbox + size]
    source, target = _flat(layout, "sMysteryGiftItem"), _flat(layout, "sBackupMysteryGiftItem")
    out[target:target + 2] = out[source:source + 2]
    out[_flat(layout, "sRTCStatusFlags")] = 0
    for copy, offset in layout.checksum_offsets.items():
        out[offset:offset + 2] = codec.sav_checksum(bytes(out[:0x8000]), layout, copy).to_bytes(2, "little")
    return bytes(out)


def verify_trade_saved_delta(before, after, *, title, expected_party, expected_dex,
                             partner_offer, own_offer, partner_player_name=None, root=ROOT):
    """Refuse every saved change outside the exact projected native transaction.

    party/dex are independently projected by the caller, never decoded from after.
    Offers are authenticated rows {slot (own only), species_marker, blob_hex}.
    G/S also needs the authenticated 11-byte staged partner trainer name (the
    native animation sender, not necessarily the incoming mon's OT name).
    """
    try:
        _need(isinstance(before, bytes) and isinstance(after, bytes)
              and len(before) == len(after) == 32790, "requires complete SaveRAM images")
        layout = codec.for_foundation(title, root=root)
        _need(all(codec.strict_checksum_witness(raw[:0x8000], layout)["valid"] for raw in (before, after)),
              "invalid checksum or disagreeing save copies")
        expected = _expected(before, layout, expected_party, expected_dex, partner_offer, own_offer, partner_player_name)
        want, actual = normalized_gameplay_cartram(expected, layout), normalized_gameplay_cartram(after, layout)
        mismatch = next((i for i, (a, b) in enumerate(zip(want, actual, strict=True)) if a != b), None)
        _need(mismatch is None, f"unexpected saved byte at CartRAM {mismatch:#06x}" if mismatch is not None else "")
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
        raise RuntimeError("trade saved delta: malformed or unsupported inputs") from exc
