"""Explicit v2 participant selection with actual ROM data and modeled host/native boundaries.

The local loader's attestation is modeled, not granted by these tests. No engine
instruction, live mailbox mutation, paired admission, or battery save is proved.
"""
import hashlib
import json

import pytest

from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256, compressed, independent_stats
from tests.rr.runtime.rr_harness import RRHarness


@pytest.fixture(scope="module")
def rom(rr_rom_path):
    data = rr_rom_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ROM_SHA256
    return data


def binding(h, rom, *, mutate_region=None):
    """Only host IO is modeled. Evidence, oracle, context and storage are real Lua."""
    revision = {
        "abi": 2, "base_rom_sha256": ROM_SHA256,
        "rom_sha1": hashlib.sha1(rom).hexdigest(), "rom_sha256": ROM_SHA256,
        "build_id": "a" * 64, "layout_sha256": "b" * 64,
    }
    h.lua.globals()._withdraw_revision = h.lua.table_from(revision)
    h.lua.globals()._withdraw_binding = h.lua.table_from(
        {**{k: v for k, v in revision.items() if k not in ("abi", "base_rom_sha256")},
         "context_generation": 7, "binding_digest": "c" * 64}
    )
    h.lua.globals()._withdraw_rom_hash = revision["rom_sha1"]
    reads = []

    def read_region(address, size):
        reads.append((address, size))
        raw = rom[address - 0x08000000:address - 0x08000000 + size]
        if mutate_region == address:
            raw = bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    h.lua.globals()._withdraw_read_region = read_region
    h.lua.globals()._withdraw_hash_hex = lambda value: hashlib.sha256(bytes.fromhex(value)).hexdigest()
    h.lua.execute("""
        _withdraw_io={
            read_region=function(a,n) return _withdraw_read_region(a,n) end,
            read_u8=memory.read_u8,
            sha256=function(raw)
                return _withdraw_hash_hex((raw:gsub('.',function(b) return string.format('%02x',b:byte()) end)))
            end,
            getromhash=function() return _withdraw_rom_hash end,
            verified_binding=function() return _withdraw_binding end,
        }
        _withdraw_module=require('rr.withdrawal_evidence')
    """)
    value = h.lua.globals()._withdraw_module.new(
        h.lua.globals()._withdraw_io, h.lua.globals()._withdraw_revision
    )
    return value, reads


def prepared(rr_repo, rom, *, mgm=False):
    h = RRHarness(rr_repo, party=(333,))
    h.seed_u8(0x0203B25A, 4 if mgm else 0)
    raw = bytearray(compressed(pid=111))
    raw[0x13] = 2
    raw = bytes(raw)
    h.seed(int(h.M.boxMonAddr(0, 0)), raw)
    evidence, reads = binding(h, rom)
    assert not isinstance(evidence, tuple), evidence
    ctx = h.lua.eval('require("rr.context")')
    if isinstance(ctx, tuple):
        ctx = ctx[0]
    mod = h.lua.eval('require("rr.storage")')
    if isinstance(mod, tuple):
        mod = mod[0]
    storage = mod.new_verified(h.M, h.MB, h.lua.globals().memory,
                               ctx.new(h.M, h.MB, h.lua.globals().memory), evidence)
    body = h.lua.table_from({"cmd": "party_mon", "key": h.key(111), "slot": 1, "box": 0, "pos": 0})
    intent = storage.prepare(body)
    assert not isinstance(intent, tuple), intent
    return h, storage, body, intent, raw, reads


def native_golden(rom, raw):
    """Independent fixture, including zero-fill/marker/PP. Never uses Lua's expected result."""
    result = bytearray(100)
    result[:28] = raw[:28]
    result[0x20:0x2B] = raw[0x1C:0x27]
    result[0x38:0x3E] = raw[0x2C:0x32]
    result[0x44:0x4C] = raw[0x32:0x3A]
    result[0x4F], result[0x55] = 128, 255
    level, stats = independent_stats(rom, raw)
    result[0x54] = level
    for offset, value in zip(range(0x56, 0x64, 2), [stats[0], *stats], strict=True):
        result[offset:offset + 2] = value.to_bytes(2, "little")
    packed = int.from_bytes(raw[0x27:0x2C], "little")
    for i in range(4):
        move = (packed >> (10 * i)) & 1023
        pp = rom[0x11521D0 + 12 * move + 4]
        result[0x2C + 2 * i:0x2E + 2 * i] = move.to_bytes(2, "little")
        result[0x34 + i] = pp + pp * 20 * ((raw[0x24] >> (2 * i)) & 3) // 100
    return bytes(result)


@pytest.mark.parametrize("mgm", [False, True])
def test_exact_prepared_destination_survives_json_restart_and_receipt(rr_repo, rom, mgm):
    h, storage, body, intent, raw, reads = prepared(rr_repo, rom, mgm=mgm)
    expected = native_golden(rom, raw)
    assert intent.schema == "rr-storage-intent-v2"
    assert intent.after_party[2].lower() == expected.hex()
    assert intent.withdrawal.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert intent.withdrawal.context.minimal_grinding is mgm
    h.lua.globals()._saved_intent = intent
    h.lua.execute("_restored_intent=require('json_codec').decode(require('json_codec').encode(_saved_intent))")
    restored = h.lua.globals()._restored_intent
    assert storage.classify(body, restored)[0] == "before"
    assert storage.apply(body, restored)
    h.engine_storage_effect(withdrawn_party=expected)
    state, proof = storage.classify(body, restored)
    assert state == "after"
    receipt = storage.receipt(body, restored, proof)
    assert receipt.schema == "rr-storage-receipt-v2" and receipt.durability == "live_ram_only"
    assert receipt.withdrawal.expected_party.lower() == expected.hex()
    restored.withdrawal.context.context_generation = 999
    assert receipt.withdrawal.context.context_generation == 7
    assert len(reads) == 15  # Immutable ROM evidence is loaded once, not reread each frame.
    assert not h.events("sync_retrieve_done")  # Participant receipt is not server publication.


@pytest.mark.parametrize("field,offset,value", [
    ("poison", 0x50, 8), ("pp", 0x34, 1), ("attack", 0x5A, 231),
    ("mail", 0x55, 0), ("builder-marker", 0x4F, 0), ("zero-padding", 0x3E, 1),
])
def test_corruption_that_old_predicate_accepted_cannot_create_receipt(rr_repo, rom, field, offset, value):
    h, storage, body, intent, raw, _ = prepared(rr_repo, rom)
    assert storage.apply(body, intent)
    wrong = bytearray(native_golden(rom, raw))
    assert wrong[offset] != value, field
    wrong[offset] = value
    h.engine_storage_effect(withdrawn_party=wrong)
    state, reason = storage.classify(body, intent)
    assert state == "diverged", field
    assert storage.receipt(body, intent, None)[0] is None
    assert storage.apply(body, intent)[0] is None  # Uncertain native lease is retained.
    assert "readback" in reason


@pytest.mark.parametrize("change", ["mgm", "frontier", "easy", "randomizer", "rom", "epoch", "revoke", "build"])
def test_changed_context_blocks_fresh_execution_and_completed_readback(rr_repo, rom, change):
    for after in (False, True):
        h, storage, body, intent, raw, _ = prepared(rr_repo, rom)
        if after:
            assert storage.apply(body, intent)
            h.engine_storage_effect(withdrawn_party=native_golden(rom, raw))
        if change in ("mgm", "easy"):
            h.seed_u8(0x0203B25A, 4 if change == "mgm" else 8)
        elif change == "frontier":
            h.seed_u8(0x0203B17A, 1)
        elif change == "randomizer":
            h.seed_u8(0x0203B17C, 1)
        elif change == "rom":
            h.lua.globals()._withdraw_rom_hash = "d" * 40
        elif change == "epoch":
            h.lua.globals()._withdraw_binding.context_generation = 8
        elif change == "build":
            h.lua.globals()._withdraw_binding.build_id = "d" * 64
        else:
            h.lua.globals()._withdraw_binding = None
        assert storage.classify(body, intent)[0] == "diverged", (change, after)
        assert storage.apply(body, intent)[0] is None
        assert storage.receipt(body, intent, None)[0] is None


@pytest.mark.parametrize("address", [0x090B6924, 0x090788FC, 0x097B98EC, 0x0915514C, 0x091521D0, 0x08252B48])
def test_changed_local_derivation_region_refuses_binding(rr_repo, rom, address):
    h = RRHarness(rr_repo)
    writes = len(h.lua.globals()._RR_WRITES)
    value, _ = binding(h, rom, mutate_region=address)
    assert value[0] is None and "region mismatch" in value[1]
    assert len(h.lua.globals()._RR_WRITES) == writes


def test_missing_binding_and_legacy_intents_never_downgrade_v2(rr_repo, rom):
    h, storage, body, intent, _, _ = prepared(rr_repo, rom)
    mod = h.lua.globals().package.loaded["rr.storage"]
    assert mod.new_verified(h.M, h.MB, h.lua.globals().memory, None, None)[0] is None
    intent.schema = "rr-storage-intent-v1"
    assert storage.classify(body, intent)[0] == "diverged"
    assert storage.apply(body, intent)[0] is None


@pytest.mark.parametrize("target", ["source", "expectation", "digest", "generation"])
def test_serialized_intent_tampering_cannot_change_expected_result(rr_repo, rom, target):
    h, storage, body, intent, _, _ = prepared(rr_repo, rom)
    if target == "source":
        intent.before_box = "00" + intent.before_box[2:]
    elif target == "expectation":
        intent.after_party[2] = "00" + intent.after_party[2][2:]
    elif target == "digest":
        intent.withdrawal.party_sha256 = "e" * 64
    else:
        intent.withdrawal.context.context_generation = 8
    assert storage.classify(body, intent)[0] == "diverged", target
    assert storage.apply(body, intent)[0] is None
    assert h.pending_native()["opcode"] == 0


def test_proof_is_plain_json_and_manifest_has_new_dependency(rr_repo, rom):
    h, _, _, intent, _, _ = prepared(rr_repo, rom)
    h.lua.globals()._saved_intent = intent
    wire = h.lua.eval("require('json_codec').encode(_saved_intent)")
    assert json.loads(wire)["withdrawal"]["context"]["rom_sha256"] == ROM_SHA256
    assert "lua/rr/withdrawal_evidence.lua" in h.manifest()


def test_context_change_inside_hash_service_refuses_preparation(rr_repo, rom):
    h, storage, body, _, _, _ = prepared(rr_repo, rom)
    # Constructor hashes have finished. Model a local service yielding and a
    # mode change occurring before it returns the source/expected digest.
    h.lua.execute("""
        local original=_withdraw_io.sha256
        _withdraw_io.sha256=function(raw)
            local result=original(raw)
            _RR_RAM[0x0203B25A]=4
            return result
        end
    """)
    result = storage.prepare(body)
    assert result[0] is None and "context changed" in result[1]
    assert h.pending_native()["opcode"] == 0


@pytest.mark.parametrize("exp", [0, 0xFFFFFFFF])
def test_native_out_of_campaign_level_is_refused_without_clamping(rr_repo, rom, exp):
    h = RRHarness(rr_repo)
    evidence, _ = binding(h, rom)
    result = evidence.prepare(compressed(exp=exp).hex())
    assert result[0] is None and "campaign domain" in result[1]


def test_readback_factory_cannot_be_retargeted_by_editing_input_manifest(rr_repo, rom):
    h, storage, body, intent, _, _ = prepared(rr_repo, rom)
    h.lua.globals()._withdraw_revision.rom_sha1 = "d" * 40
    assert storage.classify(body, intent)[0] == "before"
    h.lua.globals()._withdraw_binding.rom_sha1 = "d" * 40
    h.lua.globals()._withdraw_rom_hash = "d" * 40
    assert storage.classify(body, intent)[0] == "diverged"
