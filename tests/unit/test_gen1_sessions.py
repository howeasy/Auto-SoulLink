"""Cartridge decisions precede observable state; socket/session retries cannot bypass them."""
import asyncio
import copy
import itertools
import json
import secrets

import pytest

from server import gen1_admission as admission
from server.server import SLinkServer
from tools.gen_gen1_admission_profiles import build_profiles, outputs


def contract(a="red", b="blue"):
    profiles = admission.clean_profiles()
    return {"schema": admission.CONTRACT_SCHEMA, "players": {
        player: admission.cartridge_metadata(profiles[variant]) for player, variant in (("a", a), ("b", b))}}


def hello(spec, player="a", **changes):
    nonce = secrets.token_hex(16)
    return {"protocol": admission.PROTOCOL, "event": "hello", "player": player,
            "rom_type": spec["players"][player]["variant"].capitalize(),
            "client_nonce": nonce, "operation_id": nonce + ":hello", "seq": 0,
            "ot_id": "0000" if player == "a" else "5678", "trainer_name": player.upper(),
            "party": [], **copy.deepcopy(spec["players"][player]), **changes}


def event(gate, player="a", seq=1, **changes):
    session = gate.sessions[player]
    return {"protocol": admission.PROTOCOL, "event": "area_enter", "player": player,
            "area_id": "route_1", "admission_epoch": gate.epoch, "session_id": session.session_id,
            "seq": seq, "operation_id": session.nonce + ":" + str(seq), **changes}


def server(tmp_path, spec):
    if spec is not None:
        (tmp_path / "rom_contract.json").write_text(json.dumps(spec), encoding="utf-8")
    return SLinkServer(data_dir=str(tmp_path))


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_admitted_save_identity_survives_a_foreign_trade_lead_on_reconnect(tmp_path, variant):
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_party_codec import make_blob

    spec = contract(variant, variant)
    srv = server(tmp_path, spec)
    codec = PartyCodec(variant)
    for ot in (0x1234, 0xBEEF):
        raw = make_blob(codec, otid=ot)
        mon = codec.validate_blob(raw)
        entry = {"blob_hex": raw.hex(), "key": mon.key, "species_id": mon.species_id,
                 "hp": mon.hp, "maxHP": mon.max_hp, "level": mon.level, "slot": 0,
                 "status_cond": mon.status}
        packet = srv._gen1_wire_response("a", hello(spec, party=[entry], has_pokeballs=False), object())
        assert packet["ack"] == "ACK"
        assert srv.state.player_identity["a"] == {"ot_id": "0000", "trainer_name": "A"}
        assert mon.key in srv.state.party_keys["a"]
    assert not srv.state.identity_error


def test_generated_catalog_reproduces_all_canonical_profiles():
    for path, content in outputs(build_profiles()).items():
        assert path.read_text(encoding="utf-8") == content


def test_status_does_not_claim_admission_before_any_hello(tmp_path):
    srv = server(tmp_path, contract())
    status = srv._build_status_dict()
    assert {p["admission"] for p in status["players"].values()} == {"contract_pending"}
    assert not any(p["connected"] for p in status["players"].values())


@pytest.mark.parametrize("titles", itertools.product(("red", "blue", "yellow"), repeat=2))
@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_all_ordered_title_pairs_in_both_hello_orders(tmp_path, titles, order):
    spec = contract(*titles)
    srv = server(tmp_path, spec)
    owners = {p: object() for p in order}
    replies = {p: srv._gen1_wire_response(p, hello(spec, p), owners[p]) for p in order}
    assert {r["ack"] for r in replies.values()} == {"ACK"}
    assert replies["a"]["admission_epoch"] == replies["b"]["admission_epoch"]
    assert replies["a"]["session_id"] != replies["b"]["session_id"]
    assert srv.state._has_helld == {"a", "b"}
    for p, variant in zip(("a", "b"), titles, strict=True):
        assert srv.connected_players[p]["variant"] == variant
        assert srv.adapter_for(p)._enc_variant == variant
        response = srv._gen1_wire_response(p, event(srv._gen1_sessions, p), owners[p])
        assert response["ack"] == "ACK"
        assert srv.player_area_id[p] == "route_1"
        for command in response["commands"]:
            for key in ("admission_epoch", "session_id", "seq", "operation_id"):
                assert command[key] == response[key]


@pytest.mark.parametrize("field,value", [
    ("rom_type", "Yellow"), ("variant", "yellow"), ("final_rom_sha1", "0" * 40),
    ("content_profile_hash", "0" * 64), ("content_profile_schema", "old"),
    ("party_codec", "old"), ("patch_version", 3), ("patch_version", False),
    ("capabilities", {"panel": True, "sfx": False, "pc_trade": False}),
    ("capabilities", {}), ("client_nonce", "bad"), ("seq", True), ("seq", 1),
    ("ot_id", ""), ("ot_id", 0), ("trainer_name", ""), ("trainer_name", []),
    ("party", {}), ("party", [None] * 7), ("protocol", None),
])
def test_refused_hello_never_changes_rule_identity_or_cartridge_caches(tmp_path, field, value):
    spec = contract()
    srv = server(tmp_path, spec)
    before = (copy.deepcopy(srv.state.player_identity), srv.state.rom_type, srv.adapter,
              copy.deepcopy(srv.state.party_keys), copy.deepcopy(srv.state.party_size))
    response = srv._gen1_wire_response("a", hello(spec, **{field: value}), object())
    assert response["ack"] == "NACK" and not response["commands"]
    assert (srv.state.player_identity, srv.state.rom_type, srv.adapter,
            srv.state.party_keys, srv.state.party_size) == before
    assert not srv._player_adapters and not srv._gen1_sessions.sessions
    assert not srv.connected_players


@pytest.mark.parametrize("spec", [None, {}, {"unreadable": True}, {"players": {"a": {"fingerprint": "f" * 64}}}])
def test_missing_or_partial_fingerprint_contracts_do_not_admit_rby(tmp_path, spec):
    srv = server(tmp_path, spec)
    response = srv._gen1_wire_response("a", hello(contract()), object())
    assert response["ack"] == "NACK"
    assert not srv.is_admitted("a")
    assert not srv.state.player_identity


def test_wrong_save_reconnect_cannot_replace_the_current_owner_or_party_cache(tmp_path):
    spec = contract()
    srv = server(tmp_path, spec)
    first = object()
    assert srv._gen1_wire_response("a", hello(spec), first)["ack"] == "ACK"
    snapshot = copy.deepcopy(srv.connected_players)
    response = srv._gen1_wire_response("a", hello(spec, ot_id="FFFF"), object())
    assert response["ack"] == "NACK"
    assert srv._gen1_sessions.owns("a", first) and srv.is_admitted("a")
    assert srv.connected_players == snapshot


def test_replacement_session_rejects_old_owner_and_old_close(tmp_path):
    spec = contract()
    srv = server(tmp_path, spec)
    first, second = object(), object()
    srv._gen1_wire_response("a", hello(spec), first)
    old = event(srv._gen1_sessions)
    previous = srv._gen1_sessions.sessions["a"].session_id
    reply = srv._gen1_wire_response("a", hello(spec), second)
    assert reply["session_id"] != previous
    assert srv._gen1_wire_response("a", old, first)["ack"] == "NACK"
    assert not srv._gen1_sessions.close("a", first)
    assert srv._gen1_sessions.owns("a", second) and srv.is_admitted("a")


def test_duplicate_retries_return_original_response_without_redispatch(tmp_path, monkeypatch):
    spec = contract()
    srv = server(tmp_path, spec)
    owner = object()
    srv._gen1_wire_response("a", hello(spec), owner)
    msg = event(srv._gen1_sessions)
    original = srv._gen1_wire_response("a", msg, owner)
    monkeypatch.setattr(srv, "_dispatch", lambda *args, **kwargs: pytest.fail("duplicate dispatched twice"))
    assert srv._gen1_wire_response("a", msg, owner) == original
    conflict = {**msg, "area_id": "route_2"}
    assert srv._gen1_wire_response("a", conflict, owner)["ack"] == "NACK"


@pytest.mark.parametrize("change", [{"seq": 0}, {"seq": True}, {"seq": 2}, {"seq": 2**53},
                                   {"session_id": "old"}, {"admission_epoch": "old"},
                                   {"operation_id": "other"}, {"protocol": "old"}])
def test_bad_envelopes_do_not_advance_semantic_state(tmp_path, change):
    spec = contract()
    srv = server(tmp_path, spec)
    owner = object()
    srv._gen1_wire_response("a", hello(spec), owner)
    response = srv._gen1_wire_response("a", event(srv._gen1_sessions, **change), owner)
    assert response["ack"] == "NACK"
    assert srv.player_area_id["a"] != "route_1"


def test_contract_change_revokes_both_sessions_even_before_another_hello(tmp_path):
    spec = contract()
    srv = server(tmp_path, spec)
    owners = {p: object() for p in ("a", "b")}
    for p in owners:
        srv._gen1_wire_response(p, hello(spec, p), owners[p])
    old_epoch = srv._gen1_sessions.epoch
    msg = event(srv._gen1_sessions)
    (tmp_path / "rom_contract.json").write_text(json.dumps(contract("yellow", "blue")), encoding="utf-8")
    assert srv._gen1_wire_response("a", msg, owners["a"])["ack"] == "NACK"
    assert srv._gen1_sessions.epoch != old_epoch and not srv._gen1_sessions.sessions
    assert not srv.is_admitted("a") and not srv.is_admitted("b")


@pytest.mark.parametrize("raw", [b"[]", b"null", b'{"player":"a","player":"b"}',
    b'{"_rejected":true}',
    b'{"x":NaN}', b'{"x":1e400}', b'{"x":9007199254740992}', b'{"x":"\xff"}',
    b'{"x":"\\ud800"}', b'{"x":' + b'[' * 34 + b'0' + b']' * 34 + b'}'])
def test_invalid_wire_json_is_rejected(raw):
    with pytest.raises(admission.AdmissionError):
        admission.decode_frame(raw)


@pytest.mark.parametrize("change", ["missing-blob", "invalid-blob", "slot", "hp", "key", "duplicate", "not-object"])
def test_hello_rejects_entire_malformed_party_before_binding_identity(tmp_path, change):
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_party_codec import make_blob
    codec = PartyCodec("red")
    raw = make_blob(codec)
    mon = codec.validate_blob(raw)
    entry = {"blob_hex": raw.hex(), "key": mon.key, "species_id": mon.species_id,
             "hp": mon.hp, "maxHP": mon.max_hp, "level": mon.level, "slot": 0, "status_cond": mon.status}
    party = [entry]
    if change == "missing-blob":
        entry.pop("blob_hex")
    elif change == "invalid-blob":
        entry["blob_hex"] = "FF" * 66
    elif change in {"slot", "hp", "key"}:
        entry[change] = None
    elif change == "duplicate":
        party.append({**entry, "slot": 1})
    else:
        party = [None]
    spec = contract()
    srv = server(tmp_path, spec)
    assert srv._gen1_wire_response("a", hello(spec, party=party), object())["ack"] == "NACK"
    assert not srv.state.player_identity and not srv._gen1_sessions.sessions
    assert not srv.connected_players


def test_valid_whole_party_is_accepted_and_partial_rom_tables_cannot_replace_its_profile(tmp_path):
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_party_codec import make_blob
    codec = PartyCodec("red")
    raw = make_blob(codec)
    mon = codec.validate_blob(raw)
    entry = {"blob_hex": raw.hex(), "key": mon.key, "species_id": mon.species_id,
             "hp": mon.hp, "maxHP": mon.max_hp, "level": mon.level, "slot": 0, "status_cond": mon.status}
    spec = contract()
    srv = server(tmp_path, spec)
    response = srv._gen1_wire_response("a", hello(spec, party=[entry], rom_content={"wild": {}}), object())
    assert response["ack"] == "ACK"
    assert srv.adapter_for("a")._rom_encounters is None
    assert srv.state.party_keys["a"] == {mon.key}


@pytest.mark.asyncio
async def test_real_tcp_player_binding_oversize_resync_and_old_disconnect(tmp_path):
    spec = contract()
    srv = server(tmp_path, spec)
    listener = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0, limit=4096)
    port = listener.sockets[0].getsockname()[1]
    peers = []

    async def connect():
        pair = await asyncio.open_connection("127.0.0.1", port)
        peers.append(pair)
        return pair

    async def send(pair, payload):
        pair[1].write((json.dumps(payload) + "\n").encode())
        await pair[1].drain()
        return json.loads(await asyncio.wait_for(pair[0].readline(), 3))

    try:
        first = await connect()
        assert (await send(first, {"event": "capture", "player": "a"}))["ack"] == "NACK"
        request = hello(spec)
        first[1].write(b"x" * 5000 + b"\n" + (json.dumps(request) + "\n").encode())
        await first[1].drain()
        assert json.loads(await first[0].readline())["ack"] == "NACK"
        assert json.loads(await first[0].readline())["ack"] == "ACK"
        assert (await send(first, hello(spec, "b")))["ack"] == "NACK"
        second = await connect()
        assert (await send(second, hello(spec)))["ack"] == "ACK"
        first[1].close()
        await first[1].wait_closed()
        assert (await send(second, event(srv._gen1_sessions)))["ack"] == "ACK"
        assert srv.connected_players["a"]["connected"] and srv.is_admitted("a")
    finally:
        for _, writer in peers:
            writer.close()
            await writer.wait_closed()
        listener.close()
        await listener.wait_closed()
