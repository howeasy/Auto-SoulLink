"""Real observation batches and SQLite storage jobs; cartridge images/file receipts are synthetic."""

import copy
import hashlib
import secrets

import pytest

from server.gen1_initial_observation import inventory
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_storage import SCHEMA, expected
from server.gen1_storage_runtime import (
    COMPONENT,
    OBSERVE,
    acknowledge,
    expand_entry,
    verify_journal,
    verify_state,
)
from server.protocol import digest
from tests.unit.observation_fixture import commit, current_frame, observe, starters
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_memorial import fixture
from tests.unit.test_gen1_sessions import contract


def source(runtime, player):
    return copy.deepcopy(
        runtime.state().document()["components"]["gen1-inventory-observations"][player][
            "observation"
        ]
    )


def all_jobs(runtime):
    from server.event_reference import resolve
    rows=runtime.state().document()['components'][COMPONENT]['jobs'].values()
    return [expand_entry(runtime.journal,row) for row in sorted(rows,key=lambda row:(resolve(runtime.journal,row['origin']).revision,row['id']))]


def latest_job(runtime):
    return all_jobs(runtime)[-1]


def spare(runtime, player):
    point = source(runtime, player)
    if point["source"]["save_status"] == 0:
        from server.gen1_initial_save_runtime import prepared as initial_saved

        point["source"]["cart_hex"] = initial_saved(runtime.state().document(), player)["after"][
            "cart_hex"
        ]
        point["source"]["save_status"] = 2
    donor, _, _ = fixture(point["source"]["variant"], count=2, slot=0)
    other = bytes.fromhex(donor["fields"]["party"])
    raw = bytearray.fromhex(point["source"]["fields"]["party"])
    for base, stride in ((8, 44), (272, 11), (338, 11)):
        raw[base + stride : base + 2 * stride] = other[base + stride : base + 2 * stride]
    raw[0] = 2
    raw[2:4] = bytes([raw[52], 255])
    point["source"]["fields"]["party"] = raw.hex().upper()
    point["frame"] += 10
    commit(runtime, player, [], point=point)


def read(runtime, player, *, point=None, raw_checkpoint=None):
    command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
    observed = source(runtime, player)
    if point is not None:
        observed["source"] = copy.deepcopy(point)
    receipt = {
        "schema": OBSERVE,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": player * 32,
        "final_sha1": observed["final_sha1"],
        "host": {**observed["host"], "frame": current_frame(runtime, player)},
        "checkpoint": raw_checkpoint or checkpoint(observed["source"]["variant"]),
        "point": observed["source"],
    }
    return acknowledge(
        runtime,
        player,
        secrets.token_hex(16),
        {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": receipt,
        },
    )


def write(runtime, player, *, corrupt=False):
    command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
    job = runtime.state().document()["components"][COMPONENT]["jobs"][command["body"]["job_id"]]
    p = job["prepared"][player]
    receipt = {
        "schema": SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": p["context_generation"],
        "final_sha1": p["final_sha1"],
        "before_digest": digest(p["before"]),
        "after": copy.deepcopy(p["after"]),
        "file": {
            "schema": "slink-saveram-file-v1",
            "path": "owned/" + player + "/SaveRAM/game.sav",
            "byte_length": 0x8000,
            "sha256": "f" * 64
            if corrupt
            else hashlib.sha256(bytes.fromhex(p["after"]["cart_hex"])).hexdigest(),
            "host_profile": "bizhawk-2.11.1-gambatte-exclusive-hold-v1",
            "frame": p["frame"],
            "flushed": True,
            "readback": True,
        },
    }
    return acknowledge(
        runtime,
        player,
        secrets.token_hex(16),
        {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": receipt,
        },
    )


def complete_storage(runtime):
    """Model held images through real read/apply/file ACKs; retain next physical source."""
    physical = getattr(runtime, "test_storage_physical", {})
    for _ in range(32):
        progressed = False
        for player in ("a", "b"):
            pending = runtime.journal.pending_ids(player)
            if not pending:
                continue
            command = runtime.journal.command(player, pending[0])
            if command["body"]["cmd"] == "storage_observe":
                read(runtime, player, point=physical.get(player))
                progressed = True
            elif command["body"]["cmd"] == "storage_apply":
                job = runtime.state().document()["components"][COMPONENT]["jobs"][
                    command["body"]["job_id"]
                ]
                after = copy.deepcopy(job["prepared"][player]["after"])
                write(runtime, player)
                physical[player] = after
                progressed = True
        if not progressed:
            runtime.test_storage_physical = physical
            return physical
    raise AssertionError("storage fixture did not converge within32physical ACKsteps")


def deposit_pending(runtime, *, peer_spare=False):
    starters(runtime)
    spare(runtime, "a")
    if peer_spare:
        spare(runtime, "b")
    keys = {p: getattr(runtime.state().rules.links[0], p).key for p in ("a", "b")}
    point = source(runtime, "a")
    point["frame"] += 1
    point["source"] = expected(
        point["source"], keys["a"], "deposit", identity=runtime.state().rules.player_identity["a"]
    )
    commit(runtime, "a", [], point=point)
    return keys


@pytest.mark.parametrize("fault", ["battle", "text", "invalid_box"])
def test_unsafe_or_invalid_peer_read_never_writes_peer_and_restores_initiator(tmp_path, fault):
    from server.gen1_full_save import SYMBOLS
    from server.gen1_held_faint import PROFILES
    from server.gen1_storage_runtime import INVALID_REASON

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        keys = deposit_pending(runtime)
        point = source(runtime, "b")["source"]
        raw = checkpoint("yellow")
        if fault == "invalid_box":
            symbols = SYMBOLS["pokeyellow"]
            main = bytearray.fromhex(point["fields"]["main"])
            main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 255
            point["fields"]["main"] = main.hex().upper()
        else:
            field = "BATTLE_FLAG_ADDR" if fault == "battle" else "FONT_LOADED_ADDR"
            raw["system"][str(PROFILES["yellow"][field])] = 1
        read(runtime, "a")
        read(runtime, "b", point=point, raw_checkpoint=raw)
        job = latest_job(runtime)
        assert job["resolution"]["refusal"] == (
            "invalid-current-box" if fault == "invalid_box" else "unsafe-peer-context"
        )
        assert set(job["prepared"]) == {"a"} and not runtime.journal.pending_ids("b")
        before_peer = copy.deepcopy(job["reads"]["b"]["receipt"]["point"])
        write(runtime, "a")
        current = runtime.state()
        verify_state(current)
        verify_journal(runtime.journal, current)
        completed = expand_entry(runtime.journal,current.document()["components"][COMPONENT]["jobs"][job["id"]])
        assert completed["complete"] and completed["reads"]["b"]["receipt"]["point"] == before_peer
        assert keys["a"] in current.rules.party_keys["a"]
        assert (INVALID_REASON in current.barrier.document()["blockers"].values()) == (
            fault == "invalid_box"
        )
    finally:
        runtime.close()


def test_bad_file_ack_keeps_both_storage_keys_unusable_and_journal_unchanged(tmp_path):
    from server.protocol_journal import JournalError

    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        keys = deposit_pending(runtime)
        read(runtime, "a")
        read(runtime, "b")
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            write(runtime, "a", corrupt=True)
        assert runtime.journal.snapshot() == before
        assert all(key not in runtime.state().rules.party_keys[p] for p, key in keys.items())
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["full_box", "yellow_restriction"])
def test_cartridge_deposit_refusal_keeps_peer_containers_and_undoes_actor(tmp_path, fault):
    from server.gen1_full_save import SYMBOLS

    runtime = create_runtime(tmp_path, contract("red", "yellow"))
    try:
        keys = deposit_pending(runtime, peer_spare=True)
        point = source(runtime, "b")["source"]
        if fault == "yellow_restriction":
            main = bytearray.fromhex(point["fields"]["main"])
            symbols = SYMBOLS["pokeyellow"]
            main[symbols["wPikachuOverworldStateFlags"] - symbols["wMainDataStart"]] |= 2
            point["fields"]["main"] = main.hex().upper()
        else:
            party = bytes.fromhex(point["fields"]["party"])
            raw = bytearray(1122)
            raw[0] = 20
            raw[1:22] = bytes([party[8]] * 20 + [255])
            for slot in range(20):
                boxed = bytearray(party[8:41])
                boxed[3] = party[41]
                boxed[27:29] = slot.to_bytes(2, "big")
                raw[22 + slot * 33 : 22 + (slot + 1) * 33] = boxed
                raw[682 + slot * 11 : 682 + (slot + 1) * 11] = party[272:283]
                raw[902 + slot * 11 : 902 + (slot + 1) * 11] = party[338:349]
            point["fields"]["box"] = raw.hex().upper()
        read(runtime, "a")
        read(runtime, "b", point=point)
        job = latest_job(runtime)
        assert job["resolution"]["refusal"] == (
            "current-box-full" if fault == "full_box" else "yellow-starter-following-disabled"
        )
        assert job["prepared"]["b"]["after"]["fields"] == point["fields"]
        write(runtime, "a")
        write(runtime, "b")
        assert all(key in runtime.state().rules.party_keys[p] for p, key in keys.items())
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_boxed_grants_pair_logically_without_becoming_usable_party_keys(tmp_path, variants):
    from tests.unit.observation_fixture import checkpoint as observed, source as grant, start

    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        for player in ("a", "b"):
            raw = grant(runtime, player, delivery="box")
            point = observed(runtime, player, [raw], 140)
            commit(runtime, player, [raw], point=point)
            entry = runtime.state().document()["components"]["gen1-acquisition-settlement"][player]
            row = entry["settled"][0]
            assert row["rule"] == "exempt_grant" and row["violation"] is None
            assert row["fact"]["key"] not in runtime.state().rules.party_keys[player]
        assert len(runtime.state().rules.links) == 1
        complete_storage(runtime)
        state = runtime.state()
        verify_state(state)
        verify_journal(runtime.journal, state)
        assert all(not state.rules.party_keys[p] for p in ("a", "b"))
        assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
def test_boxed_birth_in_grave_relocates_without_party_space_or_adopting_archive(tmp_path, variants):
    from server.gen1_full_save import SYMBOLS, image
    from server.gen1_grave_storage import checksum_banks
    from server.gen1_memorial_policy import box_offset
    from tests.unit.observation_fixture import checkpoint as observed, source as grant, start

    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        start(runtime)
        for player in ("a", "b"):
            row = grant(runtime, player, delivery="box", call=130, finish=145)
            for witness in ("call", "return"):
                row["receipt"][witness]["point"]["current_box"] = 139
            before = row["receipt"]["call"]["point"]
            seed = observed(runtime, player, [], 120, party=before["party_hex"])
            seed["source"]["fields"]["box"] = before["box_hex"]
            symbols = SYMBOLS[
                "pokeyellow" if variants[0 if player == "a" else 1] == "yellow" else "pokered"
            ]
            main = bytearray.fromhex(seed["source"]["fields"]["main"])
            main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 139
            seed["source"]["fields"]["main"] = main.hex().upper()
            cart = bytearray.fromhex(seed["source"]["cart_hex"])
            for box in range(12):
                cart[box_offset(box) : box_offset(box) + 1122] = b"\0\xff" + bytes(1120)
            checksum_banks(cart, {2, 3})
            seed["source"]["cart_hex"] = cart.hex().upper()
            seed["source"]["cart_hex"] = image(seed["source"]).hex().upper()
            seed["source"]["save_status"] = 2
            commit(runtime, player, [], point=seed)
            commit(runtime, player, [row], point=observed(runtime, player, [row], 150))
            complete_storage(runtime)
            jobs = all_jobs(runtime)
            eviction = next(j for j in jobs if j["kind"] == "grave_evict" and j["actor"] == player)
            assert eviction["complete"] and eviction["prepared"][player]["destination_box"] == 0
            post = eviction["prepared"][player]["after"]
            assert (
                inventory(post, runtime.state().rules.player_identity[player])["party_count"] == 6
            )
            assert bytes.fromhex(post["fields"]["box"])[0] == 0
            assert (
                not runtime.state()
                .document()["components"]
                .get("gen1-grave-reservations", {})
                .get(player)
            )
        assert len(runtime.state().rules.links) == 1
        assert not runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
        assert all(not runtime.state().rules.party_keys[p] for p in ("a", "b"))
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_reserved_grave_pc_undo_advances_only_its_exact_owned_archive_head(tmp_path):
    from server.gen1_full_save import SYMBOLS, image
    from server.gen1_grave_storage import checksum_banks
    from server.gen1_memorial_policy import box_offset
    from server.gen1_retirement_runtime import acknowledge as retire_ack
    from server.gen1_storage_runtime import _prepare
    from server.protocol_journal import JournalError
    from tests.unit.observation_fixture import checkpoint as observed
    from tests.unit.test_gen1_grant_receipt import DATA, receipt as granted
    from tests.unit.test_gen1_retirement_runtime import (
        observed as retire_read,
        written as retire_write,
    )

    runtime = create_runtime(tmp_path, contract("yellow", "red"))
    try:
        starters(runtime)
        old = source(runtime, "a")["source"]
        site = next(k for k, v in DATA["titles"]["yellow"]["sites"].items() if v["yellow_only"])
        grant = granted("yellow", site, existing=1, ot_id="0000", boxed_before=0)
        grant.update(
            context_generation="a" * 32,
            physical_instance="1" * 32,
            final_sha1=runtime.contract["players"]["a"]["final_rom_sha1"],
        )
        grant["call"]["frame"] = 120
        grant["return"]["frame"] = 130
        prior = bytes.fromhex(old["fields"]["party"])
        for witness in ("call", "return"):
            raw = bytearray.fromhex(grant[witness]["point"]["party_hex"])
            raw[1] = prior[1]
            for start, length in ((8, 44), (272, 11), (338, 11)):
                raw[start : start + length] = prior[start : start + length]
            grant[witness]["point"]["party_hex"] = raw.hex().upper()
        row = {"kind": "grant", "receipt": grant}
        from server.gen1_initial_save_runtime import prepared as initial_saved

        acquired_point = observed(runtime, "a", [row], 140)
        acquired_point["source"]["cart_hex"] = initial_saved(runtime.state().document(), "a")[
            "after"
        ]["cart_hex"]
        acquired_point["source"]["save_status"] = 2
        commit(runtime, "a", [row], point=acquired_point)
        _, message = retire_read(runtime)
        retire_ack(runtime, "a", secrets.token_hex(16), message)
        _, message = retire_write(runtime)
        retire_ack(runtime, "a", secrets.token_hex(16), message)
        point = source(runtime, "a")
        point["source"] = message["receipt"]["after"]
        point["frame"] += 1
        commit(runtime, "a", [], point=point)
        spare(runtime, "a")
        point = source(runtime, "a")
        raw = point["source"]
        cart = bytearray.fromhex(raw["cart_hex"])
        cart[box_offset(0) : box_offset(0) + 1122] = bytes.fromhex(raw["fields"]["box"])
        raw["fields"]["box"] = cart[box_offset(11) : box_offset(11) + 1122].hex().upper()
        cart[box_offset(11) : box_offset(11) + 2] = b"\0\xff"
        checksum_banks(cart, {2, 3})
        main = bytearray.fromhex(raw["fields"]["main"])
        symbols = SYMBOLS["pokeyellow"]
        main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] = 139
        raw["fields"]["main"] = main.hex().upper()
        raw["cart_hex"] = cart.hex().upper()
        raw["cart_hex"] = image(raw).hex().upper()
        point["frame"] += 1
        commit(runtime, "a", [], point=point)
        key = runtime.state().rules.links[0].a.key
        point = source(runtime, "a")
        point["source"] = expected(
            point["source"],
            key,
            "deposit",
            identity=runtime.state().rules.player_identity["a"],
            reserved_boxes=(),
        )
        point["frame"] += 1
        commit(runtime, "a", [], point=point)
        read(runtime, "a")
        read(runtime, "b")
        job = latest_job(runtime)
        assert job["resolution"]["refusal"] == "reserved-archive-deposit"
        damaged = copy.deepcopy(job)
        damaged["reads"]["a"]["grave_head"]["reservation_digest"] = "f" * 64
        with pytest.raises(JournalError, match="prior reservation"):
            _prepare(damaged, runtime.state().document())
        write(runtime, "a")
        write(runtime, "b")
        document = runtime.state().document()
        assert (
            document["components"]["gen1-grave-reservations"]["a"]["kind"] == "storage_compensation"
        )
        assert key in runtime.state().rules.party_keys["a"]
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


def test_manual_dead_link_withdrawal_rearchives_without_new_death_or_usable_key(tmp_path):
    from server.gen1_faint_runtime import acknowledge as faint_ack
    from server.gen1_memorial_runtime import acknowledge as memorial_ack
    from server.state import LinkStatus
    from tests.unit.test_gen1_faint_runtime import signal_batch
    from tests.unit.test_gen1_memorial_runtime import completion

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        spare(runtime, "a")
        spare(runtime, "b")
        points = {p: source(runtime, p) for p in ("a", "b")}
        signals = signal_batch(runtime, "a")
        signals["signals"][0]["frame"] = 121
        signals["signals"][-1]["frame"] = 122
        raw = bytearray.fromhex(points["a"]["source"]["fields"]["party"])
        raw[9:11] = b"\0\0"
        signals["signals"][-1]["point"]["party_hex"] = raw.hex().upper()
        points["a"]["source"]["fields"]["party"] = raw.hex().upper()
        points["a"]["frame"] = 123
        observe(runtime, "a", inventory=points["a"], signals=signals)
        command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
        mons = [
            r
            for r in inventory(points["b"]["source"], runtime.state().rules.player_identity["b"])[
                "members"
            ]
            if r["location"] == "party"
        ]
        pre = {
            "schema": "gen1-party-readback-v1",
            "variant": "yellow",
            "save_id": "0000",
            "save_name": "SAME",
            "party_count": len(mons),
            "party": [m["blob_hex"] for m in mons],
            "species_list": [bytes.fromhex(m["blob_hex"])[0] for m in mons] + [255],
            "battle_flag": 0,
            "active_slot": None,
            "battle_hp": None,
        }
        post = copy.deepcopy(pre)
        post["party"][0] = post["party"][0][:2] + "0000" + post["party"][0][6:]
        faint_ack(
            runtime,
            "b",
            secrets.token_hex(16),
            {
                "event": "command_ack",
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "outcome": "ACK",
                "receipt": {"schema": "gen1-force-faint-receipt-v1", "before": pre, "after": post},
            },
        )
        raw = bytearray.fromhex(points["b"]["source"]["fields"]["party"])
        raw[9:11] = b"\0\0"
        points["b"]["source"]["fields"]["party"] = raw.hex().upper()
        for player in ("a", "b"):
            command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
            observed = points[player]
            receipt = {
                "schema": "rby-memorial-observation-v1",
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "context_generation": player * 32,
                "final_sha1": observed["final_sha1"],
                "host": {**observed["host"], "frame": observed["frame"]},
                "checkpoint": checkpoint("yellow"),
                "point": observed["source"],
            }
            memorial_ack(
                runtime,
                player,
                secrets.token_hex(16),
                {
                    "event": "command_ack",
                    "command_id": command["command_id"],
                    "command_sequence": command["command_sequence"],
                    "outcome": "ACK",
                    "receipt": receipt,
                },
            )
            _, message = completion(runtime, player)
            memorial_ack(runtime, player, secrets.token_hex(16), message)
            points[player]["source"] = message["receipt"]["after"]
        key = runtime.state().rules.links[0].a.key
        points["a"]["frame"] += 1
        commit(runtime, "a", [], point=points["a"])
        point = source(runtime, "a")
        point["frame"] += 1
        point["source"] = expected(
            point["source"],
            key,
            "withdraw",
            identity=runtime.state().rules.player_identity["a"],
            reserved_boxes=(),
        )
        old_deaths = copy.deepcopy(
            runtime.state().document()["components"]["gen1-faint-settlement"]
        )
        commit(runtime, "a", [], point=point)
        assert runtime.state().rules.links[0].status == LinkStatus.MEMORIAL
        read(runtime, "a")
        write(runtime, "a")
        state = runtime.state()
        verify_state(state)
        verify_journal(runtime.journal, state)
        job = latest_job(runtime)
        assert job["kind"] == "archive_return" and job["complete"]
        assert key not in state.rules.party_keys["a"]
        assert state.document()["components"]["gen1-faint-settlement"] == old_deaths
        restored = next(
            m
            for m in inventory(job["prepared"]["a"]["after"], state.rules.player_identity["a"])[
                "members"
            ]
            if m["key"] == key
        )
        assert restored["box"] == 11
        assert (
            state.document()["components"]["gen1-grave-reservations"]["a"]["kind"]
            == "storage_compensation"
        )
        assert (
            next(
                m
                for m in inventory(job["prepared"]["a"]["after"], state.rules.player_identity["a"])[
                    "members"
                ]
                if m["key"] == key
            )["location"]
            == "box"
        )
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()


@pytest.mark.parametrize("variants", [("yellow", "yellow"), ("red", "blue"), ("blue", "yellow")])
@pytest.mark.parametrize(
    "peer_has_spare", [False, True], ids=["last-member-compensation", "paired-deposit"]
)
def test_observed_deposit_synchronizes_or_canonically_undoes_after_verified_peer_read(
    tmp_path, variants, peer_has_spare
):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        starters(runtime)
        spare(runtime, "a")
        if peer_has_spare:
            spare(runtime, "b")
        keys = {p: getattr(runtime.state().rules.links[0], p).key for p in ("a", "b")}
        point = source(runtime, "a")
        point["frame"] += 1
        point["source"] = expected(
            point["source"],
            keys["a"],
            "deposit",
            identity=runtime.state().rules.player_identity["a"],
        )
        commit(runtime, "a", [], point=point)
        for p in ("a", "b"):
            assert keys[p] not in runtime.state().rules.party_keys[p]
            read(runtime, p)
        job = latest_job(runtime)
        assert job["resolution"]["refusal"] == (None if peer_has_spare else "last-party-member")
        write(runtime, "a")
        assert not runtime.state().document()["components"][COMPONENT]["jobs"][job["id"]][
            "complete"
        ]
        write(runtime, "b")
        state = runtime.state()
        verify_state(state)
        verify_journal(runtime.journal, state)
        completed = expand_entry(runtime.journal,state.document()["components"][COMPONENT]["jobs"][job["id"]])
        assert completed["complete"]
        for p in ("a", "b"):
            physical = next(
                m
                for m in inventory(
                    completed["prepared"][p]["after"], state.rules.player_identity[p]
                )["members"]
                if m["key"] == keys[p]
            )
            assert physical["location"] == ("box" if peer_has_spare else "party")
            assert (keys[p] in state.rules.party_keys[p]) == (not peer_has_spare)
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        verify_state(runtime.state())
        verify_journal(runtime.journal, runtime.state())
    finally:
        runtime.close()
