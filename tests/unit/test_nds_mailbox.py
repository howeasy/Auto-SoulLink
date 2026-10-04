"""Committed NDS ABI header -> host-C arena dump -> Lua mailbox reader integration.

The arena image and every offset/size/enum value come from the REAL committed headers
(`patch/src/nds/common/abi.h`, `patch/src/nds/gen4/beacon.h`) compiled for the host;
the Lua module under test is the shipped `lua/nds/mailbox.lua`. The memory reader is a
boundary simulation (a byte buffer with injected faults), the way the witness test's is.

The helpers `_gcc`, the io forms and the fault-injection idea are COPIED from
tests/unit/test_nds_native_witness.py rather than imported: that module's compiler
discovery owns its own skip reason (`NDS_WITNESS_HOST_CC_ABSENT`) and its own fixtures,
and one test module importing another's helpers makes one gate fail with the other's
name. Everything else here is this card's own.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
GEN4 = ROOT / "patch/src/nds/gen4"
MODULE = ROOT / "lua/nds/mailbox.lua"
BEACON = GEN4 / "beacon.c"
BASE = 0x02468000  # arbitrary fake-memory address, not a game address


def _gcc():
    # Same discovery contract as test_nds_native_witness.py / test_nds_common_producers.py.
    for candidate in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if candidate:
            return candidate
    bases = [ROOT]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True, timeout=30)
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for path in sorted((base / ".cache/build-tools").glob(pattern)):
                if (path.parent.parent / "libexec").is_dir():
                    return str(path)
    reason = "NDS_MAILBOX_HOST_CC_ABSENT: set SLINK_HOST_GCC; C-to-Lua integration did not run"
    if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


HARNESS = r'''
#include "abi.h"
#include "beacon.h"
#include <stdio.h>
#include <string.h>

_Static_assert(SLINK_CAP_MATCH_CALL == (1 << 6), "shared capability vocabulary ends at bit 6");

#define EPOCH 9u
#define GENERATION 4u

static unsigned char arena[SLINK_ARENA_SIZE];

/* One service visit's published bytes, in the ROM's own order (beacon.c:243-256):
   header repair first, then the title block published last. */
static void stamp(void) {
  SlinkMailboxV2 *m = (SlinkMailboxV2 *)(void *)arena;
  SlinkGen4Title *t = (SlinkGen4Title *)(void *)(arena + SLINK_GEN4_TITLE_OFFSET);
  m->signature = SLINK_SIGNATURE;
  m->abi_version = (uint16_t)SLINK_ABI_VERSION;
  m->capabilities = SLINK_GEN4_CAPABILITIES;
  m->session_epoch = EPOCH;
  m->producer_phase = SLINK_PHASE_IDLE;
  m->reserved = GENERATION;
  m->status = SLINK_ST_OK;
  for (unsigned i = 0; i < sizeof m->args; i++) m->args[i] = (uint8_t)(i * 5u + 1u);
  for (unsigned i = 0; i < sizeof m->result; i++) m->result[i] = (uint8_t)(0xA0u + i);
  t->magic = SLINK_GEN4_TITLE_MAGIC;
  t->version = (uint16_t)SLINK_GEN4_TITLE_VERSION;
  t->size = (uint16_t)sizeof(SlinkGen4Title);
  t->cookie = 0xDEADBEEFu;
  t->identity = 0x11223344u;
  t->delta = 0x240u;
  t->generation = GENERATION;
  t->registrations = 2u;
}

static void layout(void) {
#define VALUE(k,v) printf("%s=%u\n",k,(unsigned)(v))
#define MB(f) VALUE("mailbox_" #f,offsetof(SlinkMailboxV2,f))
  VALUE("arena_size",SLINK_ARENA_SIZE);
  VALUE("mailbox_offset",SLINK_MAILBOX_OFFSET);VALUE("mailbox_size",sizeof(SlinkMailboxV2));
  VALUE("witness_offset",SLINK_WITNESS_OFFSET);VALUE("witness_size",sizeof(SlinkTradeWitnessV2));
  VALUE("blob_offset",SLINK_BLOB_OFFSET);VALUE("blob_size",SLINK_BLOB_SIZE);
  VALUE("text_offset",SLINK_TEXT_OFFSET);VALUE("text_size",SLINK_TEXT_SIZE);
  VALUE("menu_offset",SLINK_MENU_OFFSET);VALUE("menu_size",SLINK_MENU_SIZE);
  VALUE("info_offset",SLINK_INFO_OFFSET);VALUE("info_size",SLINK_INFO_SIZE);
  VALUE("control_offset",SLINK_CONTROL_OFFSET);VALUE("control_size",SLINK_CONTROL_SIZE);
  VALUE("reserved_offset",SLINK_RESERVED_OFFSET);
  MB(signature);MB(abi_version);MB(opcode);MB(seq);MB(status);MB(ack_seq);MB(reason);
  MB(args);MB(result);MB(capabilities);MB(session_epoch);MB(producer_phase);MB(reserved);
  VALUE("signature",SLINK_SIGNATURE);VALUE("abi",SLINK_ABI_VERSION);
  VALUE("phase_uncertain",SLINK_PHASE_UNCERTAIN);
  VALUE("caps_shared",SLINK_CAP_MATCH_CALL * 2u - 1u);
  VALUE("caps_reserved",0xFF80u & ~((SLINK_CAP_MATCH_CALL * 2u) - 1u));
  /* Gen 4 title-private block: TEST SIDE ONLY. The shared module must not decode it. */
  VALUE("title_offset",SLINK_GEN4_TITLE_OFFSET);VALUE("title_size",SLINK_GEN4_TITLE_SIZE);
  VALUE("title_magic",SLINK_GEN4_TITLE_MAGIC);VALUE("title_version",SLINK_GEN4_TITLE_VERSION);
  VALUE("title_cookie_field",SLINK_GEN4_TITLE_COOKIE_FIELD);
  VALUE("title_identity_field",SLINK_GEN4_TITLE_IDENTITY_FIELD);
  VALUE("title_delta_field",SLINK_GEN4_TITLE_DELTA_FIELD);
  VALUE("title_generation_field",SLINK_GEN4_TITLE_GENERATION_FIELD);
  VALUE("title_registrations_field",SLINK_GEN4_TITLE_REGISTRATIONS_FIELD);
}

int main(int argc,char **argv) {
  if (argc == 2 && !strcmp(argv[1], "layout")) { layout(); return 0; }
  for (unsigned i = 0; i < SLINK_ARENA_SIZE; i++) arena[i] = (unsigned char)(i * 7u + 3u);
  stamp();
  fputs("ARENA ", stdout);
  for (unsigned i = 0; i < SLINK_ARENA_SIZE; i++) printf("%02x", (unsigned)arena[i]);
  puts("");
  return 0;
}
'''

# Reader forms under test. "u32_only" has no byte reader at all: it must be refused
# rather than quietly composed from a narrower width.
FORMS = {
    "bytes": ("read_bytes",),
    "u8": ("read_u8",),
    "u8_u16": ("read_u8", "read_u16"),
    "u8_u32": ("read_u8", "read_u32"),
    "bytes_u32": ("read_bytes", "read_u32"),
    "bytes_u16_u32": ("read_bytes", "read_u16", "read_u32"),
    "u32_only": ("read_u32",),
}

FAULTS = ["nil", "short", "hole", "invalid_byte", "throw", "u8_invalid",
          "u32_out_of_range", "u16_negative", "envelope_change"]


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("nds-mailbox-host")
    source = tmp / "arena.c"
    source.write_text(HARNESS, encoding="utf-8")
    exe = tmp / "arena.exe"
    cc = _gcc()
    built = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", str(COMMON), "-I", str(GEN4),
                            str(source), "-o", str(exe)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return exe


def run(exe, *args):
    done = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def compiled(harness):
    return {name: int(value) for name, value in
            (line.split("=") for line in run(harness, "layout").splitlines())}


@pytest.fixture(scope="module")
def image(harness):
    parts = run(harness).split()
    assert parts[0] == "ARENA"
    return bytes.fromhex(parts[1])


def dense(table, n):
    return [table[i] for i in range(1, n + 1)]


def put(raw, offset, value, width=4):
    data = bytearray(raw)
    data[offset:offset + width] = value.to_bytes(width, "little")
    return bytes(data)


def mailbox_put(raw, compiled, field, value, width=4):
    return put(raw, compiled["mailbox_" + field], value, width)


def build(data, *, form="bytes", abi=3, source=None, layout=None, signed=False, flip=None):
    """A reader over `data`. `flip` is (arena offset, nth occurrence): the value the nth
    read of that address returns is changed, which is how an envelope change between the
    two samples is injected."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(source if source is not None else MODULE.read_text(encoding="utf-8"))
    names = FORMS[form]
    counts = dict.fromkeys(set(names), 0)
    seen = {}

    def scalar(address, width, name):
        counts[name] += 1
        value = int.from_bytes(data[address - BASE:address - BASE + width], "little")
        if flip is not None and address - BASE == flip[0]:
            seen[address] = seen.get(address, 0) + 1
            if seen[address] == flip[1]:
                value = (value + 1) % (1 << (8 * width))
        if signed and width == 4 and value >= 0x80000000:
            value -= 1 << 32
        return value

    def read_bytes(address, n):
        counts["read_bytes"] += 1
        return lua.table_from(list(data[address - BASE:address - BASE + n]))

    def read_u8(address):
        counts["read_u8"] += 1
        return data[address - BASE]

    supplied = {"read_bytes": read_bytes, "read_u8": read_u8,
                "read_u16": lambda a: scalar(a, 2, "read_u16"),
                "read_u32": lambda a: scalar(a, 4, "read_u32")}
    config = {"base": BASE, "abi": abi}
    if layout is not None:
        config["layout"] = layout
    obj, reason = module.new(lua.table_from({n: supplied[n] for n in names}), lua.table_from(config))
    return lua, module, obj, reason, counts


def reader(data, **kwargs):
    lua, module, obj, reason, counts = build(data, **kwargs)
    assert obj is not None and reason is None, reason
    return lua, module, obj, counts


# ------------------------------------------------------------------ layout oracle

def test_layout_table_equals_compiled_header_and_is_a_fresh_copy(compiled):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    exported = dict(module.layout().items())
    assert exported == {k: v for k, v in compiled.items() if k in exported}, (
        {k for k in compiled if k not in exported}, {k for k in exported if k not in compiled})
    # Every module key is pinned by the committed header, and the module does not carry
    # Gen 4's title-private vocabulary: that extent is derived in this test only.
    assert "title_offset" not in exported and "title_size" not in exported
    assert exported["reserved_offset"] == compiled["title_offset"]
    changed = module.layout()
    changed["mailbox_capabilities"] = 0
    assert dict(module.layout().items()) == exported


# --------------------------------------------------------------- accepted reading

@pytest.mark.parametrize("form", sorted(FORMS))
def test_header_and_snapshot_accept_the_committed_image(compiled, image, form):
    if form == "u32_only":
        pytest.skip("no byte reader: covered by test_u32_only_io_is_refused")
    _, _, obj, counts = reader(image, form=form)
    env, reason = obj.header()
    assert reason is None and env["signature"] == compiled["signature"]
    assert env["abi_version"] == compiled["abi"] == 3
    assert env["session_epoch"] == 9 and env["phase"] == 0 and env["reserved"] == 4
    assert env["capabilities"] == 0 and env["caps_shared"] == 0 and env["reserved_bits"] == 0
    # One envelope is five u32 scalars (signature, capabilities, epoch, phase, reserved)
    # plus abi_version at u16; forms without a u32 reader compose all six from bytes.
    expected = 5 if "read_u32" in FORMS[form] else 0
    assert counts.get("read_u32", 0) == expected
    if "read_bytes" in FORMS[form]:
        assert counts.get("read_u8", 0) == 0, "a byte-table reader is never used per byte"
    snap, reason = obj.snapshot()
    assert reason is None and snap["abi"] == 3
    envelope = snap["envelope"]
    assert envelope["session_epoch"] == env["session_epoch"]
    assert envelope["reserved"] == env["reserved"] and envelope["phase"] == env["phase"]
    # The payload copy is the mailbox verbatim: raw, undecoded, private to the caller.
    start = compiled["mailbox_offset"]
    size = compiled["mailbox_size"]
    assert dense(snap["bytes"], size) == list(image[start:start + size])
    assert snap["bytes"][size + 1] is None
    assert counts.get("read_u32", 0) == 3 * expected, "one header sample + two envelope samples per snapshot"


def test_byte_only_form_composes_every_width_from_the_byte_reader(compiled, image):
    # One envelope is signature+abi+caps+epoch+phase+reserved = 22 bytes.
    _, _, obj, counts = reader(image, form="u8")
    env, reason = obj.header()
    assert reason is None and env["abi_version"] == 3 and counts["read_u8"] == 22
    snap, reason = obj.snapshot()
    assert reason is None and counts["read_u8"] == 22 + (22 + compiled["mailbox_size"] + 22)  # header, then snapshot
    # A binary string is an equally valid byte-reader output.
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    io = lua.table_from({"read_bytes": lambda a, n: image[a - BASE:a - BASE + n]})
    obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3}))
    assert why is None
    snap, why = obj.snapshot()
    assert why is None and dense(snap["bytes"], compiled["mailbox_size"]) == \
        list(image[:compiled["mailbox_size"]])


def test_signed_u32_representations_normalize_to_unsigned(compiled, image):
    stamped = mailbox_put(image, compiled, "capabilities", 0x80000001)
    stamped = mailbox_put(stamped, compiled, "session_epoch", 0xF1234567)
    stamped = mailbox_put(stamped, compiled, "reserved", 0xFFFFFFFF)
    for form in ("bytes_u32", "u8_u32"):
        _, _, obj, _ = reader(stamped, form=form)
        env, reason = obj.header()
        assert reason is None, form
        assert env["capabilities"] == 0x80000001 and env["caps_shared"] == 1
        assert env["session_epoch"] == 0xF1234567 and env["reserved"] == 0xFFFFFFFF
        _, _, signed, _ = reader(stamped, form=form, signed=True)
        signed_env, reason = signed.header()
        assert reason is None, form
        assert dict(signed_env.items()) == dict(env.items())


def test_u32_only_io_is_refused_instead_of_a_silent_narrow_composition(image):
    _, _, obj, reason, _ = build(image, form="u32_only")
    assert obj is None and reason == "config:reader"


@pytest.mark.parametrize("form", ["bytes_u32", "u8_u32"])
def test_missing_u16_is_composed_from_bytes_and_never_from_u32(compiled, image, form):
    # abi_version is u16 at +0x04; a u32 reader may not stand in for it.
    _, _, obj, counts = reader(image, form=form)
    env, reason = obj.header()
    assert reason is None and env["abi_version"] == 3
    assert counts.get("read_u32", 0) == 5, "the u16 envelope scalar must not cost a u32 read"
    # the HIGH byte is read too: 0x0103 is refused as a different ABI (a low-byte-only composition would accept it)
    stamped = mailbox_put(image, compiled, "abi_version", 0x0103, 2)
    _, _, obj, counts = reader(stamped, form=form)
    env, reason = obj.header()
    assert env is None and reason == "abi:mismatch" and counts.get("read_u32", 0) == 5


# ----------------------------------------------------------------------- refusals

@pytest.mark.parametrize("entry", ["header", "snapshot"])
@pytest.mark.parametrize("field,value,width,reason", [
    ("signature", 0, 4, "mailbox:signature"),
    ("abi_version", 2, 2, "abi:mismatch"),
    ("producer_phase", 6, 4, "mailbox:phase"),
])
def test_corrupt_envelope_is_named(compiled, image, entry, field, value, width, reason):
    stamped = mailbox_put(image, compiled, field, value, width)
    _, _, obj, _ = reader(stamped)
    result, actual = getattr(obj, entry)()
    assert result is None and actual == reason, (entry, field, actual)


def test_abi_mismatch_covers_every_non_three_word(compiled, image):
    for word in (0, 2, 4, 0xFFFF):
        stamped = mailbox_put(image, compiled, "abi_version", word, 2)
        _, _, obj, _ = reader(stamped)
        for entry in ("header", "snapshot"):
            result, reason = getattr(obj, entry)()
            assert result is None and reason == "abi:mismatch", (word, entry)


@pytest.mark.parametrize("field", ["capabilities", "session_epoch", "producer_phase", "reserved"])
def test_envelope_change_between_the_two_samples_is_refused(compiled, image, field):
    offset = compiled["mailbox_" + field]
    _, _, obj, _ = reader(image, form="bytes_u32", flip=(offset, 2))
    result, reason = obj.snapshot()
    assert result is None and reason == "mailbox:changed", field
    # header() takes one sample and makes no coherence claim at all.
    _, _, plain, _ = reader(image, form="bytes_u32", flip=(offset, 2))
    env, reason = plain.header()
    assert env is not None and reason is None, field


def test_payload_bytes_are_outside_the_coherence_claim(compiled, image):
    # DOCUMENTED LIMIT, not an expectation that this is correct: the mailbox has no
    # revision counter, so a payload byte changed inside the copied window is invisible.
    # opcode/args are bound by the caller's seq/ack_seq protocol instead.
    torn = bytearray(image)
    torn[compiled["mailbox_args"]] ^= 0xFF
    _, _, obj, _ = reader(bytes(torn))
    snap, reason = obj.snapshot()
    assert reason is None
    assert snap["bytes"][compiled["mailbox_args"] + 1] == torn[compiled["mailbox_args"]]


def test_capabilities_are_informational_and_never_a_gate(compiled, image):
    for caps in (0, 1, 0x80, 0xFFFFFFFF, 0x000F0081, 0xFFFF0000):
        stamped = mailbox_put(image, compiled, "capabilities", caps)
        for entry in ("header", "snapshot"):
            _, _, obj, _ = reader(stamped)
            result, reason = getattr(obj, entry)()
            assert reason is None, (caps, entry, reason)
        _, _, obj, _ = reader(stamped)
        env, reason = obj.header()
        assert env["capabilities"] == caps
        assert env["caps_shared"] == caps & 0x7F
        assert env["reserved_bits"] == caps & 0xFF80


# ---------------------------------------------------------------------- regions

def test_region_copies_exact_bytes_and_never_decodes_the_title_block(compiled, image):
    _, _, obj, _ = reader(image)
    offset, size = compiled["title_offset"], compiled["title_size"]
    assert offset == compiled["reserved_offset"] and size == 64
    payload, reason = obj.region(obj, offset, size)
    assert reason is None and dense(payload, size) == list(image[offset:offset + size])
    assert payload[size + 1] is None
    # The Gen 4 title block is decoded HERE, not by the shared module: nothing in the
    # module's layout names the title vocabulary, and region() returns bytes only.
    assert int.from_bytes(image[offset:offset + 4], "little") == compiled["title_magic"]
    assert int.from_bytes(image[offset + 4:offset + 6], "little") == compiled["title_version"]
    assert int.from_bytes(image[offset + 6:offset + 8], "little") == size
    published = dense(payload, size)
    for name, expected in (("cookie", 0xDEADBEEF), ("identity", 0x11223344),
                           ("delta", 0x240), ("generation", 4), ("registrations", 2)):
        field = compiled["title_" + name + "_field"]
        assert int.from_bytes(bytes(published[field:field + 4]), "little") == expected, name
    for region in ("witness", "blob", "text", "menu", "info", "control"):
        start, extent = compiled[region + "_offset"], compiled[region + "_size"]
        payload, reason = obj.region(obj, start, extent)
        assert reason is None and dense(payload, extent) == list(image[start:start + extent])


@pytest.mark.parametrize("offset,length", [
    (0, 0), (0xE00, 0), (0x1000, 1), (0xFFF, 2), (0x1000, 0), (0xFFFF, 1),
])
def test_region_out_of_arena_is_refused(image, offset, length):
    _, _, obj, _ = reader(image)
    result, reason = obj.region(obj, offset, length)
    assert result is None and reason == "region:range", (offset, length)


@pytest.mark.parametrize("bad", [None, -1, 1.5, "8", True])
def test_region_rejects_non_integer_bounds(image, bad):
    _, _, obj, _ = reader(image)
    for offset, length in ((bad, 8), (8, bad), (0xE00, bad)):
        result, reason = obj.region(obj, offset, length)
        assert result is None and reason == "region:range", (offset, length)


# ------------------------------------------------------------------ fault matrix

def faulty_io(lua, data, compiled, fault):
    seen = {}

    def scalar(address, width):
        value = int.from_bytes(data[address - BASE:address - BASE + width], "little")
        if fault == "u32_out_of_range" and width == 4:
            return 1 << 32
        if fault == "u16_negative" and width == 2:
            return -1
        if fault == "envelope_change" and address == BASE + compiled["mailbox_session_epoch"]:
            seen[address] = seen.get(address, 0) + 1
            if seen[address] == 2:
                value += 1
        return value

    def read_bytes(address, n):
        if fault == "throw":
            raise RuntimeError("simulated unreadable memory")
        if fault == "nil":
            return None
        values = list(data[address - BASE:address - BASE + n])
        if fault == "short":
            values.pop()
        output = lua.table_from(values)
        if fault in ("hole", "invalid_byte"):
            # Index 1 is inside every read this module makes (a u16 composition is two
            # bytes); a wide block keeps the fault away from its first element.
            output[1 if n < 12 else 12] = None if fault == "hole" else 256
        return output

    def read_u8(address):
        return None if fault == "u8_invalid" else data[address - BASE]

    scalars = {"read_u16": lambda a: scalar(a, 2), "read_u32": lambda a: scalar(a, 4)}
    if fault == "u8_invalid":
        # read_bytes takes precedence inside the module, so the byte path has to be absent
        # for this fault to be reachable at all.
        return lua.table_from({"read_u8": read_u8} | scalars)
    return lua.table_from({"read_bytes": read_bytes, "read_u8": read_u8} | scalars)


@pytest.mark.parametrize("fault", FAULTS)
def test_every_fault_returns_a_reason_and_never_a_bare_nil(compiled, image, fault):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    obj, why = module.new(faulty_io(lua, image, compiled, fault),
                          lua.table_from({"base": BASE, "abi": 3}))
    assert obj is not None and why is None, fault
    # envelope_change is a coherent refusal that only the two-sampled entry can see; every
    # other fault is unreadable memory for all three entries.
    # Which reader each entry uses decides which faults it can see: header() reads six SCALARS (the
    # injected u16/u32 readers), snapshot() reads scalars AND the payload block, region() reads only a
    # block. So a byte-reader fault is invisible to header(), a scalar fault is invisible to region(),
    # and only the two-sampled snapshot() can see the envelope flip.
    scalar_faults = {"u32_out_of_range", "u16_negative"}
    outcome = {
        "header": "read:error" if fault in scalar_faults else None,
        "snapshot": "mailbox:changed" if fault == "envelope_change" else "read:error",
        "region": None if fault in scalar_faults | {"envelope_change"} else "read:error",
    }
    for entry in ("header", "snapshot", "region"):
        call = (lambda: obj.region(obj, 0xE00, 0x40)) if entry == "region" else getattr(obj, entry)
        result = call()
        assert isinstance(result, tuple) and len(result) == 2, (fault, entry, result)
        value, reason = result
        if outcome[entry] is None:
            assert value is not None and reason is None, (fault, entry, reason)
        else:
            assert value is None and reason == outcome[entry], (fault, entry, reason)


# ------------------------------------------------------- configuration and purity

def test_no_globals_and_configuration_is_copied(image):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    before = set(lua.globals().keys())
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    assert set(lua.globals().keys()) == before, "module must not create globals"
    io = lua.table_from({"read_bytes": lambda a, n: lua.table_from(list(image[a - BASE:a - BASE + n]))})
    for change, reason in (({"abi": 4}, "abi:unsupported"), ({"abi": 2}, "abi:unsupported"),
                           ({"abi": None}, "abi:unsupported"),
                           ({"base": -1}, "config:base"), ({"base": 0xFFFFFFF0}, "config:base"),
                           ({"base": 0xFFFFFFFF}, "config:base"),
                           ({"base": "0x100"}, "config:base")):
        obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3} | change))
        assert obj is None and why == reason, (change, why)
    for bad in (5, "read", lua.table_from({}), True):
        for name in ("read_bytes", "read_u8", "read_u16", "read_u32"):
            supplied = {name: bad, "read_u8": lambda a: 0} if name != "read_u8" else {name: bad}
            obj, why = module.new(lua.table_from(supplied), lua.table_from({"base": BASE, "abi": 3}))
            assert obj is None and why == "config:reader", (bad, name, why)
    # A later mutation of the caller's config must not retarget a live reader: BASE+0x100000
    # is outside the fake memory, so a retargeted read would fail rather than succeed.
    config = lua.table_from({"base": BASE, "abi": 3})
    obj, why = module.new(io, config)
    assert why is None
    config["base"] = BASE + 0x100000
    config["abi"] = 4
    env, why = obj.header()
    assert env is not None and why is None
    assert set(lua.globals().keys()) == before


def test_supplied_layout_must_match_in_both_directions(compiled, image):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    io = lua.table_from({"read_bytes": lambda a, n: lua.table_from(list(image[a - BASE:a - BASE + n]))})
    size = compiled["mailbox_size"]
    supplied = lua.table_from(dict(module.layout().items()))
    obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3, "layout": supplied}))
    assert obj is not None and why is None
    supplied["mailbox_size"] = 8  # mutated after construction: the layout is copied
    snap, why = obj.snapshot()
    assert snap is not None and why is None
    # bytes is 1-based over the copy, which starts at mailbox_offset 0.
    assert snap["bytes"][size] == image[size - 1] and snap["bytes"][size + 1] is None
    for change in ({"mailbox_capabilities": 0x44}, {"arena_size": 0x2000},
                   {"mailbox_size": 8}, {"extra": 1}):
        candidate = dict(module.layout().items()) | change
        obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3,
                                                  "layout": lua.table_from(candidate)}))
        assert obj is None and why == "config:layout", (change, why)


# --------------------------------------------------------------- red controls

def assert_torn_refused(image, compiled, source):
    _, _, obj, _, _ = build(image, form="bytes_u32", source=source,
                            flip=(compiled["mailbox_session_epoch"], 2))
    result, reason = obj.snapshot()
    assert result is None and reason == "mailbox:changed", reason


def test_revert_control_dropping_the_second_envelope_sample_is_caught(image, compiled):
    source = MODULE.read_text(encoding="utf-8")
    old = "local after=envelope()"
    assert source.count(old) == 1
    assert_torn_refused(image, compiled, source)
    with pytest.raises(AssertionError):
        assert_torn_refused(image, compiled, source.replace(old, "local after=before"))


def test_revert_control_accepting_any_abi_is_caught(image):
    source = MODULE.read_text(encoding="utf-8")
    old = "    if config.abi~=L.abi then return nil,\"abi:unsupported\" end\n"
    assert source.count(old) == 1
    for abi in (2, 4, 5):
        _, _, obj, reason, _ = build(image, abi=abi, source=source)
        assert obj is None and reason == "abi:unsupported"
        _, _, obj, reason, _ = build(image, abi=abi, source=source.replace(old, ""))
        assert obj is not None and reason is None, (abi, reason)


def test_revert_control_using_capabilities_as_a_gate_is_caught(image):
    source = MODULE.read_text(encoding="utf-8")
    old = "        if not uint(env.phase,layout.phase_uncertain) then return nil,\"mailbox:phase\" end\n"
    assert source.count(old) == 1

    def accepts(source_text):
        _, _, obj, _, _ = build(image, source=source_text)
        env, reason = obj.header()
        assert env is not None and reason is None, reason

    accepts(source)
    mutant = source.replace(old, "        if env.caps_shared==0 then return nil,\"mailbox:capabilities\" end\n")
    with pytest.raises(AssertionError):
        accepts(mutant)


# -------------------------------------------- SOURCE falsifier for the reader's premise

PUBLISH_SIGNATURE = "Slink_NDS_Publish(SlinkGen4State"


def publish_fields(text):
    """The `t->field = ...` statements of the publish function, in source order."""
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if PUBLISH_SIGNATURE in line)
    fields = []
    for line in lines[begin + 1:]:
        if line.strip() == "}":
            break
        match = re.match(r"\s*t->(\w+)\s*=", line)
        if match:
            fields.append(match.group(1))
    return fields


def test_beacon_publishes_the_title_magic_last():
    # The reader's torn-read argument assumes the ROM publishes the title block's magic
    # last, so a host sampling mid-visit sees a valid header over a stale payload rather
    # than a valid header over a torn one (beacon.c:181-183,181-195).
    fields = publish_fields(BEACON.read_text(encoding="utf-8"))
    assert len(fields) > 1, "no publish statements found: the falsifier would be vacuous"
    assert len(set(fields)) == len(fields)
    assert fields[-1] == "magic", fields


def test_beacon_publish_order_control_swapped_lines_require_red():
    text = BEACON.read_text(encoding="utf-8")
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if PUBLISH_SIGNATURE in line)
    body = [i for i in range(begin + 1, len(lines)) if re.match(r"\s*t->\w+\s*=", lines[i])]
    assert "magic" in lines[body[-1]]
    swapped = list(lines)
    swapped[body[0]], swapped[body[-1]] = swapped[body[-1]], swapped[body[0]]
    mutated = "\n".join(swapped) + ("\n" if text.endswith("\n") else "")
    assert publish_fields(mutated)[-1] != "magic"
    with pytest.raises(AssertionError):
        assert publish_fields(mutated)[-1] == "magic"
