"""Actual NDS C producer -> byte dumps -> Lua witness reader integration.

The engine and memory I/O are boundary simulations. The producer, record
bindings, ABI layout and C durability predicate are the committed implementation.
Gen 3 compatibility references lua/gen3/native.lua:628-669, not a rewritten oracle.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
MODULE = ROOT / "lua/nds/native_witness.lua"
BASE = 0x02468000  # arbitrary fake-memory address, not a game address


def _gcc():
    # Same discovery contract as test_nds_common_producers.py; no test-internal import.
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
    reason = "NDS_WITNESS_HOST_CC_ABSENT: set SLINK_HOST_GCC; C-to-Lua integration did not run"
    if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


HARNESS = r'''
#include "trade_producer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define OLD_PID 0x11223344u
#define OLD_OT 0x55667788u
#define NEW_PID 0xFEDCBA98u
#define NEW_OT 0x87654321u
typedef struct { SlinkMailboxV2 m; SlinkTradeWitnessV2 w; } Image;
_Static_assert(offsetof(Image,w)==SLINK_WITNESS_OFFSET,"dump witness placement");
static Image image;
static SlinkTradeProducer producer;
static SlinkRecordStageV1 stage;
static SlinkTradeEngine engine;
static SlinkDecoder decoder;
static unsigned tick, polls;
static int pre_result, scene_result, mode, pending_polls, foreign;

static int safe(void *p) { (void)p; return 1; }
static int locate(void *p,uint32_t pid,uint32_t ot) {
  (void)p; return pid==OLD_PID && ot==OLD_OT ? 0 : -1;
}
static int pre_start(void *p) { (void)p; return 1; }
static int pre_poll(void *p) { (void)p; return pre_result; }
static int scene_start(void *p,unsigned slot,const uint8_t *data,uint16_t n) {
  (void)p; return slot==0 && n==engine.binding->party_len
    && memcmp(data,stage.record,n)==0;
}
static int scene_poll(void *p) { (void)p; return scene_result; }
static int save_begin(void *p) { (void)p; return 1; }
static int save_poll(void *p) {
  (void)p; polls++;
  if (mode==2 || polls <= (unsigned)pending_polls) return SLINK_SAVEPOLL_PENDING;
  return mode==1 ? SLINK_SAVEPOLL_FAIL : SLINK_SAVEPOLL_OK;
}
static int received(void *p,unsigned slot,uint32_t *pid,uint32_t *ot) {
  (void)p;(void)slot;*pid=foreign ? NEW_PID^1u : NEW_PID;*ot=NEW_OT;return 1;
}
static uint32_t frame(void *p) { (void)p;return tick; }
static int read_decoded(void *p,const uint8_t *r,uint16_t n,uint16_t off,uint32_t *out) {
  (void)p;if ((unsigned)off+4>n)return 0;*out=0;
  for(unsigned i=0;i<4;i++)*out|=(uint32_t)(r[off+i]^0xA5u)<<(8*i);
  return 1;
}
static int verify_record(void *p,const uint8_t *r,uint16_t n) {
  (void)p;return n==engine.binding->party_len && r[6]==0x5Au;
}
static void word(uint8_t *p,uint32_t n) { memcpy(p,&n,4); }
static void dump(const char *label) {
  printf("SNAP %s %d ",label,slink_trade_success_is_durable(&image.w,1,2,NEW_PID,NEW_OT));
  const uint8_t *p=(const uint8_t *)&image;
  for(unsigned i=0;i<sizeof image;i++)printf("%02x",p[i]);
  puts("");
}
static void service(const char *label) {
  tick++;
  slink_trade_service(&producer,&image.m,&image.w,&stage,&engine);
  dump(label); /* every service call is observable, including PENDING */
}
static void layout(void) {
#define VALUE(k,v) printf("%s=%u\n",k,(unsigned)(v))
#define MB(f) VALUE("mailbox_" #f,offsetof(SlinkMailboxV2,f))
#define W(f) VALUE("witness_" #f,offsetof(SlinkTradeWitnessV2,f))
  VALUE("mailbox_size",sizeof(SlinkMailboxV2));VALUE("witness_size",sizeof(SlinkTradeWitnessV2));
  VALUE("witness_offset",SLINK_WITNESS_OFFSET);
  MB(signature);MB(abi_version);MB(session_epoch);MB(producer_phase);
  W(session_epoch);W(visit_id);W(token);W(revision);W(visit_flags);W(milestones);
  W(milestone_seq);W(final_result);W(save_status);W(milestone_frame);
  W(old_pid);W(old_otid);W(received_pid);W(received_otid);
  VALUE("token_size",sizeof(image.w.token));VALUE("milestone_count",SLINK_MILESTONE_COUNT);
  VALUE("signature",SLINK_SIGNATURE);VALUE("abi_nds",SLINK_ABI_VERSION);
  VALUE("pre_save_ok",1u<<SLINK_PRE_SAVE_OK);VALUE("commit_entered",1u<<SLINK_COMMIT_ENTERED);
  VALUE("scene_evolution_done",1u<<SLINK_SCENE_EVOLUTION_DONE);
  VALUE("post_save_ok",1u<<SLINK_POST_SAVE_OK);VALUE("final_result",1u<<SLINK_FINAL_RESULT);
  VALUE("success_milestones",SLINK_SUCCESS_MILESTONES);
  VALUE("save_ok",SLINK_SAVE_OK);VALUE("save_pending",SLINK_SAVE_PENDING);VALUE("save_failed",SLINK_SAVE_FAILED);
  VALUE("phase_done",SLINK_PHASE_DONE);VALUE("phase_uncertain",SLINK_PHASE_UNCERTAIN);
  VALUE("result_committed",SLINK_TRADE_COMMITTED);VALUE("result_unchanged",SLINK_TRADE_UNCHANGED);
  VALUE("result_uncertain",SLINK_TRADE_UNCERTAIN);VALUE("visit_flags",SLINK_VISIT_ACCEPTED|SLINK_PRE_SAVE_CONSENT);
}
int main(int argc,char **argv) {
  if(argc==2 && !strcmp(argv[1],"layout")){layout();return 0;}
  if(argc!=4)return 90;
  mode=atoi(argv[2]);pending_polls=atoi(argv[3]);
  engine.binding=atoi(argv[1])==4 ? &slink_binding_gen4_pk4 : &slink_binding_gen5_pk5;
  decoder.read_u32=read_decoded;decoder.verify=verify_record;engine.decoder=&decoder;
  engine.safe_field=safe;engine.locate=locate;engine.start_pre_save=pre_start;engine.poll_pre_save=pre_poll;
  engine.start_scene=scene_start;engine.poll_scene=scene_poll;engine.post_save_begin=save_begin;
  engine.post_save_poll=save_poll;engine.received_key=received;engine.frame=frame;
  engine.save_timeout_frames=mode==2 ? 4 : 50;
  engine.pre_save_timeout_frames=mode==9 ? 7 : 0;
  stage.layout_version=SLINK_NDS_STAGE_LAYOUT;stage.binding_id=engine.binding->id;
  stage.stage_len=engine.binding->party_len;stage.generation=engine.binding->generation;
  stage.flags=SLINK_STAGE_RAW_ENCRYPTED;stage.claimed_pid=NEW_PID;stage.claimed_otid=NEW_OT;
  for(unsigned i=0;i<stage.stage_len;i++)stage.record[i]=(uint8_t)(i*7u+3u);
  word(stage.record,NEW_PID);word(stage.record+0x0C,NEW_OT^0xA5A5A5A5u);stage.record[6]=0x5A;
  slink_trade_advertise(&image.m);
  image.m.session_epoch=7;image.m.seq=1;image.m.opcode=SLINK_OP_TRADE_PREPARE;
  word(image.m.args+4,OLD_PID);word(image.m.args+8,OLD_OT);word(image.m.args+12,8);
  for(unsigned i=0;i<16;i++)image.m.args[16+i]=(uint8_t)(i+9);
  service("prepare");
  if(mode==4){pre_result=-1;service("refused");return 0;}
  /* mode 9: the pre-save leg consents, then the host's own bound expires with the save still
     unfinished. Nothing was mutated, so the producer finishes UNCHANGED from TP_PRE_SAVE:
     FINAL_RESULT only, bound to the PREPARE sequence, save_status 0, phase DONE. */
  if(mode==9){
    pre_result=2;service("consent");
    for(unsigned i=0;i<64 && image.m.producer_phase==SLINK_PHASE_PRE_SAVE;i++)service("expire");
    if(image.m.producer_phase==SLINK_PHASE_PRE_SAVE)return 94;
    return 0;
  }
  pre_result=2;service("consent");pre_result=1;service("ready");
  if(mode==5){image.m.seq=3;image.m.opcode=SLINK_OP_TRADE_WITHDRAW;service("withdrawn");return 0;}
  image.m.seq=2;image.m.opcode=SLINK_OP_TRADE_SCENE;service("scene");
  /* mode 6: scene fails BEFORE COMMIT_ENTERED -> bits 17, UNCERTAIN. */
  if(mode==6){scene_result=-1;service("scenefail");return 0;}
  /* mode 7: engine reports a different slot at commit entry -> cancel_scene ->
     bits 17, UNCHANGED. Commit entry is refused, so no marker is written. */
  if(mode==7){
    if(slink_trade_commit_entered(&producer,&image.w,1,&engine))return 93;
    dump("cancel");scene_result=1;service("cancelled");return 0;
  }
  if(!slink_trade_commit_entered(&producer,&image.w,0,&engine))return 91;
  /* mode 8: commit marker written, then the engine hands back a foreign identity ->
     bits 19 (no scene/evolution), UNCERTAIN. NOT reachable with bits 17. */
  if(mode==8){foreign=1;dump("commit");scene_result=1;service("foreign");return 0;}
  dump("commit");scene_result=1;service("save");
  if(mode==3){image.m.session_epoch=8;image.m.seq=3;image.m.opcode=SLINK_OP_TRADE_STATUS;service("stale");return 0;}
  for(unsigned i=0;i<100 && image.m.producer_phase==SLINK_PHASE_SCENE;i++)service("poll");
  if(image.m.producer_phase==SLINK_PHASE_SCENE)return 92;
  return 0;
}
'''


@pytest.fixture(scope="module")
def producer(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("nds-witness-host")
    source = tmp / "producer.c"
    source.write_text(HARNESS, encoding="utf-8")
    exe = tmp / "producer.exe"
    cc = _gcc()
    built = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(COMMON),
                            str(source), "-o", str(exe)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return exe


def run(producer, *args):
    done = subprocess.run([str(producer), *map(str, args)], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def layout(producer):
    return {name: int(value) for name, value in (line.split("=") for line in run(producer, "layout").splitlines())}


def trace(producer, generation=5, mode=0, pending=3):
    rows = []
    for line in run(producer, generation, mode, pending).splitlines():
        tag, label, success, raw = line.split()
        assert tag == "SNAP"
        rows.append((label, int(success), bytes.fromhex(raw)))
    return rows


def context(lua):
    return lua.table_from({"epoch": 7, "visit": 8, "pid": 0x11223344, "otid": 0x55667788,
                           "opaque": lua.table_from(list(range(9, 25))), "prepare_seq": 1, "scene_seq": 2,
                           "incoming": lua.table_from({"pid": 0xFEDCBA98, "otid": 0x87654321}), "seen": 0})


def reader(raw, *, abi=3, source=None, torn=False, scalar=False, signed=False):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(source if source is not None else MODULE.read_text(encoding="utf-8"))
    data = bytearray(raw)
    offsets = module.layout()
    revision_address = BASE + offsets["witness_offset"] + offsets["witness_revision"]
    calls = 0

    def read_value(address, width):
        nonlocal calls
        offset = address - BASE
        if offset < 0 or offset + width > len(data):
            raise RuntimeError("outside fake memory")
        value = int.from_bytes(data[offset:offset + width], "little")
        if address == revision_address and width == 2:
            calls += 1
            if torn and calls == 2:
                value += 2
        return value - (1 << 32) if signed and width == 4 and value >= (1 << 31) else value

    io = {"read_u16": lambda a: read_value(a, 2), "read_u32": lambda a: read_value(a, 4)}
    if scalar:
        io["read_u8"] = lambda a: read_value(a, 1)
    else:
        io["read_bytes"] = lambda a, n: lua.table_from(list(data[a - BASE:a - BASE + n]))
    obj, reason = module.new(lua.table_from(io), lua.table_from({"base": BASE, "abi": abi}))
    assert obj is not None and reason is None
    return lua, module, obj, data


def assert_pending_contract(producer, layout, source=None):
    rows = trace(producer)
    pending = [raw for _, _, raw in rows if raw[layout["witness_offset"] + layout["witness_save_status"]] == 2]
    assert len(pending) == 3, "producer must expose all three PENDING service calls"
    for raw in pending:
        lua, module, obj, _ = reader(raw, source=source)
        snapshot, reason = obj.read(context(lua), 2)
        assert snapshot is not None and reason is None, f"legitimate ABI-3 PENDING rejected: {reason}"
        assert snapshot["saved"] == 2
        success, _ = module.success(snapshot, 1, 2, 0xFEDCBA98, 0x87654321)
        assert success is False
        legacy = bytearray(raw)
        at = layout["mailbox_abi_version"]
        legacy[at:at + 2] = (2).to_bytes(2, "little")
        assert legacy[layout["witness_offset"]:] == raw[layout["witness_offset"]:]
        lua, _, obj, _ = reader(legacy, abi=2, source=source)
        snapshot, reason = obj.read(context(lua), 2)
        assert snapshot is None and reason.startswith("abi:"), reason


def test_abi3_accepts_real_pending_save_and_abi2_rejects_same_witness(producer, layout):
    assert_pending_contract(producer, layout)


@pytest.mark.parametrize("generation", [4, 5])
@pytest.mark.parametrize("mode,outcome", [(0, "COMMITTED"), (1, "UNCERTAIN"), (2, "UNCERTAIN"),
                                         (3, "UNCERTAIN"), (4, "UNCHANGED"), (5, "UNCHANGED"),
                                         (6, "UNCERTAIN"), (7, "UNCHANGED"), (8, "UNCERTAIN"),
                                         (9, "UNCHANGED")])
def test_every_producer_service_snapshot_and_terminal_predicate(producer, generation, mode, outcome):
    rows = trace(producer, generation, mode)
    seen = 0
    final_seq = 1 if mode in (4, 9) else 3 if mode == 5 else 2
    for label, c_success, raw in rows:
        lua, module, obj, _ = reader(raw)
        ctx = context(lua)
        ctx["seen"] = seen
        snapshot, reason = obj.read(ctx, final_seq)
        assert ctx["seen"] == seen, "reader must not mutate transaction state"
        if label == "stale":
            assert snapshot is None and reason == "identity:mailbox_epoch"
            classification, why = module.classify(None, seen)
            assert classification == "UNCERTAIN" and why is None
        else:
            assert snapshot is not None and reason is None, (generation, mode, label, reason)
            seen = snapshot["bits"]
            assert snapshot["pending"] == (snapshot["result"] == 0)
            classification, why = module.classify(snapshot, seen)
            assert why is None
            if snapshot["saved"] == 2:
                assert snapshot["pending"] and classification == "UNCERTAIN"
            assert classification == snapshot["classification"]
        success, why = module.success(snapshot, 1, 2, 0xFEDCBA98, 0x87654321)
        assert bool(success) == bool(c_success), (generation, mode, label)
        assert (why is None) is bool(success)
    assert classification == outcome
    assert rows[-1][1] == (1 if outcome == "COMMITTED" else 0)


def test_pre_save_timeout_witness_is_accepted_and_classified_unchanged(producer, layout):
    # The host's own pre-save bound expiring is a refusal BEFORE any mutation, so the producer
    # finishes the visit UNCHANGED out of TP_PRE_SAVE: FINAL_RESULT only, bound to the PREPARE
    # sequence, save_status 0, phase DONE -- never UNCERTAIN, which the reader reserves for a
    # commit the engine may already have performed. Distinct from the engine's own pre-save
    # refusal (mode 4): consent was recorded first, so the visit still carries PRE_SAVE_CONSENT.
    rows = trace(producer, mode=9)
    assert [label for label, _, _ in rows][:2] == ["prepare", "consent"]
    assert [label for label, _, _ in rows][-1] == "expire"
    for _, c_success, raw in rows:
        assert c_success == 0
        lua, _, obj, _ = reader(raw)
        snapshot, reason = obj.read(context(lua), 1)
        assert snapshot is not None and reason is None, reason
    base = layout["witness_offset"]
    raw = rows[-1][2]
    assert int.from_bytes(raw[base + layout["witness_milestones"]:][:4], "little") == layout["final_result"]
    assert raw[base + layout["witness_final_result"]] == layout["result_unchanged"]
    assert raw[base + layout["witness_save_status"]] == 0
    assert int.from_bytes(raw[base + layout["witness_visit_flags"]:][:2], "little") == layout["visit_flags"]
    lua, module, obj, _ = reader(raw)
    snapshot, reason = obj.read(context(lua), 1)
    assert reason is None
    assert snapshot["bits"] == layout["final_result"] and snapshot["flags"] == layout["visit_flags"]
    assert snapshot["result"] == layout["result_unchanged"] and snapshot["saved"] == 0
    assert snapshot["phase"] == layout["phase_done"] and snapshot["pending"] is False
    assert snapshot["classification"] == "UNCHANGED" and snapshot["durable_success"] is False
    assert snapshot["milestone_seq"][5] == 1
    assert module.success(snapshot, 1, 2, 0xFEDCBA98, 0x87654321)[0] is False
    # The timeout is bound to the PREPARE's sequence, so reading it as the scene sequence is
    # refused: a consumer cannot re-label the visit by guessing which command finished it.
    assert obj.read(context(lua), 2) == (None, "sequence:milestone")
    # Consent without PRE_SAVE_OK is not durability: it records that a save was agreed to, not
    # that one happened, and classify() must not read it as progress.
    assert module.classify(lua.table_from({"bits": layout["final_result"], "result": layout["result_unchanged"]}), 0) == ("UNCHANGED", None)


def test_all_offsets_constants_and_sizes_equal_compiled_header(layout):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    assert dict(module.layout().items()) == layout
    # Exported tables are copies, so one caller cannot retarget another reader.
    changed = module.layout()
    changed["witness_revision"] = 0
    assert dict(module.layout().items()) == layout


def test_abi2_layout_matches_compiled_gen3_header(tmp_path, layout):
    # Compile headers in separate translation units: NDS-2 forbids including both.
    body = HARNESS.split("static void layout(void) {", 1)[1].split("int main", 1)[0]
    body = body.replace('VALUE("save_pending",SLINK_SAVE_PENDING);', "")
    source = tmp_path / "gen3_layout.c"
    source.write_text('#include "abi.h"\n#include <stdio.h>\n'
                      'static struct { SlinkMailboxV2 m; SlinkTradeWitnessV2 w; } image;\n'
                      'static void layout(void) {' + body + '\nint main(void){layout();return 0;}\n', encoding="utf-8")
    exe = tmp_path / "gen3_layout.exe"
    done = subprocess.run([_gcc(), "-std=c11", "-Wall", "-Wextra", "-Werror", "-I",
                           str(ROOT / "patch/src/trade_targets"), str(source), "-o", str(exe)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    actual = {k: int(v) for k, v in (line.split("=") for line in run(exe).splitlines())}
    expected = dict(layout, abi_nds=2)
    del expected["save_pending"]
    assert actual == expected


def test_torn_snapshot_and_odd_zero_revision_are_not_accepted(producer, layout):
    raw = trace(producer)[-1][2]
    lua, _, obj, _ = reader(raw, torn=True)
    snapshot, reason = obj.read(context(lua), 2)
    assert snapshot is None and reason == "snapshot:revision"
    for revision in (0, 3):
        modified = bytearray(raw)
        at = layout["witness_offset"] + layout["witness_revision"]
        modified[at:at + 2] = revision.to_bytes(2, "little")
        lua, _, obj, _ = reader(modified)
        snapshot, reason = obj.read(context(lua), 2)
        assert snapshot is None and reason == "snapshot:revision"


@pytest.mark.parametrize("scalar,signed", [(False, False), (True, False), (True, True)])
def test_both_io_forms_preserve_unsigned_identity(producer, layout, scalar, signed):
    raw = trace(producer)[-1][2]
    if signed:
        raw = put(raw, layout, "mailbox_session_epoch", 0xF1234567, 4, witness=False)
        raw = put(raw, layout, "witness_session_epoch", 0xF1234567, 4)
    lua, module, obj, _ = reader(raw, scalar=scalar, signed=signed)
    ctx = context(lua)
    if signed:
        ctx["epoch"] = 0xF1234567
    snapshot, reason = obj.read(ctx, 2)
    assert snapshot is not None and reason is None
    assert snapshot["received_pid"] == 0xFEDCBA98 and snapshot["received_otid"] == 0x87654321
    assert module.success(snapshot, 1, 2, 0xFEDCBA98, 0x87654321) == (True, None)
    assert module.success(snapshot, 1, 2, 0xFEDCBA99, 0x87654321)[0] is False


def test_missing_wider_reads_fall_back_to_the_byte_reader(producer):
    raw = next(data for label, _, data in trace(producer) if label == "save")
    for form in ("bytes", "u8", "bytes_u32"):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        module = lua.execute(MODULE.read_text(encoding="utf-8"))
        io = {}
        if form == "u8":
            io["read_u8"] = lambda a: raw[a - BASE]
        else:
            io["read_bytes"] = lambda a, n, runtime=lua: runtime.table_from(list(raw[a - BASE:a - BASE + n]))
        if form == "bytes_u32":
            io["read_u32"] = lambda a: int.from_bytes(raw[a - BASE:a - BASE + 4], "little")
        obj, reason = module.new(lua.table_from(io), lua.table_from({"base": BASE, "abi": 3}))
        assert reason is None
        snapshot, reason = obj.read(context(lua), 2)
        assert snapshot is not None and reason is None, (form, reason)


def put(raw, layout, field, value, width=1, *, witness=True):
    data = bytearray(raw)
    offset = (layout["witness_offset"] if witness else 0) + layout[field]
    data[offset:offset + width] = value.to_bytes(width, "little")
    return data


def assert_pending_final_refused(producer, layout, source=None):
    # A real pre-save refusal has FINAL_RESULT only and UNCHANGED. Adding PENDING
    # violates precisely the new ABI rule, without another post-save guard masking it.
    raw = trace(producer, mode=4)[-1][2]
    raw = put(raw, layout, "witness_save_status", 2)
    lua, _, obj, _ = reader(raw, source=source)
    snapshot, reason = obj.read(context(lua), 1)
    assert snapshot is None, "PENDING plus FINAL_RESULT was accepted"
    assert reason is not None


def test_pending_is_forbidden_with_post_save_or_final_result(producer, layout):
    assert_pending_final_refused(producer, layout)
    saving = next(raw for label, _, raw in trace(producer) if label == "save")
    for bits, result in ((15, 0), (23, 3), (31, 1)):
        raw = put(saving, layout, "witness_milestones", bits, 4)
        raw = put(raw, layout, "witness_final_result", result)
        lua, _, obj, _ = reader(raw)
        snapshot, reason = obj.read(context(lua), 2)
        assert snapshot is None and reason == "abi:pending_final"


def test_revert_control_removing_pending_allowance_breaks_real_producer_trace(producer, layout):
    source = MODULE.read_text(encoding="utf-8")
    old = "local pending_allowed = abi == 3 and saved == layout.save_pending"
    assert source.count(old) == 1
    assert_pending_contract(producer, layout, source)
    mutant = source.replace(old, "local pending_allowed = false")
    with pytest.raises(AssertionError, match="legitimate ABI-3 PENDING rejected"):
        assert_pending_contract(producer, layout, mutant)


def test_revert_control_removing_final_bit_clause_accepts_corrupt_producer_dump(producer, layout):
    source = MODULE.read_text(encoding="utf-8")
    old = "local pending_final = (bits & (layout.post_save_ok | layout.final_result)) ~= 0"
    assert source.count(old) == 1
    assert_pending_final_refused(producer, layout, source)
    mutant = source.replace(old, "local pending_final = false")
    with pytest.raises(AssertionError, match="PENDING plus FINAL_RESULT was accepted"):
        assert_pending_final_refused(producer, layout, mutant)


def legacy_accepts(raw, layout, final_seq):
    """Execute the actual Gen 3 reader body, without modifying or importing its module.

    SOURCE: lua/gen3/native.lua:628-669; integer :28-30 and word :483-487.
    Only its I/O/mailbox/context boundary dependencies are injected here.
    """
    native = (ROOT / "lua/gen3/native.lua").read_text(encoding="utf-8")
    start = "local function trade_witness(t, final_seq)"
    start_int = "local function integer(v, maximum)"
    start_word = "local function word(bytes, offset, width)"
    for marker in (start, "function self:trade_visit()", start_int, "local function clone(t)",
                   start_word, "-- FR/LG durable trade"):
        assert native.count(marker) == 1, f"gen3 native.lua marker not unique/present: {marker!r}"
    function = start + native.split(start, 1)[1].split("function self:trade_visit()", 1)[0]
    int_code = start_int + native.split(start_int, 1)[1].split("local function clone(t)", 1)[0]
    word_code = start_word + native.split(start_word, 1)[1].split("-- FR/LG durable trade", 1)[0]
    # Readable failure instead of a Lua syntax error if the extraction leaks past word().
    assert word_code.count("return ") == 1 and word_code.rstrip().endswith("end"), word_code
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    wrapper = lua.execute("return function(io,trade_fields,cc,mb,trade_base)\n"
                          "local self={mailbox=function() return mb end}\n"
                          + int_code + word_code + function + "\nreturn trade_witness end")
    wf = {k.removeprefix("witness_"): v for k, v in layout.items() if k.startswith("witness_")}
    cc = {"SLINK_WITNESS_OFFSET": layout["witness_offset"], "SLINK_PHASE_DONE": layout["phase_done"],
          "SLINK_PHASE_UNCERTAIN": layout["phase_uncertain"], "SLINK_SUCCESS_MILESTONES": 31, "SLINK_SAVE_OK": 1}
    mb = {"session_epoch": int.from_bytes(raw[layout["mailbox_session_epoch"]:layout["mailbox_session_epoch"] + 4], "little"),
          "producer_phase": int.from_bytes(raw[layout["mailbox_producer_phase"]:layout["mailbox_producer_phase"] + 4], "little")}
    io = lua.table_from({"read_u16": lambda a: int.from_bytes(raw[a - BASE:a - BASE + 2], "little"),
                         "read_bytes": lambda a, n: lua.table_from(list(raw[a - BASE:a - BASE + n]))})
    function = wrapper(io, lua.table_from(wf), lua.table_from(cc), lua.table_from(mb), BASE)
    return function(context(lua), final_seq) is not None


@pytest.mark.parametrize("saved", [0, 1, 2, 255, 7])
def test_abi2_matches_existing_gen3_reader_save_rules(producer, layout, saved):
    accepted = rejected = 0
    for mode in (0, 1, 4, 5):
        final_seq = 1 if mode == 4 else 3 if mode == 5 else 2
        for _, _, data in trace(producer, mode=mode):
            raw = put(data, layout, "mailbox_abi_version", 2, 2, witness=False)
            raw = put(raw, layout, "witness_save_status", saved)
            expected = legacy_accepts(raw, layout, final_seq)
            lua, _, obj, _ = reader(raw, abi=2)
            snapshot, reason = obj.read(context(lua), final_seq)
            assert (snapshot is not None) == expected, (mode, saved, reason)
            assert (reason is None) == expected
            accepted += expected
            rejected += not expected
    assert accepted > 0
    if saved == 1:
        assert rejected == 0  # SAVE_OK is legal throughout these genuine producer paths.
    else:
        assert rejected > 0


@pytest.mark.parametrize("field,value,width,reason", [
    ("witness_session_epoch", 8, 4, "identity:witness"),
    ("witness_visit_id", 9, 4, "identity:witness"),
    ("witness_old_pid", 0, 4, "identity:witness"),
    ("witness_old_otid", 0, 4, "identity:witness"),
    ("witness_token", 0, 1, "identity:token"),
    ("witness_milestones", 63, 4, "witness:range"),
    ("witness_visit_flags", 4, 2, "witness:range"),
    ("witness_final_result", 4, 1, "witness:range"),
    ("witness_save_status", 0, 1, "abi:pre_save_status"),
    ("witness_milestone_seq", 9, 2, "sequence:milestone"),
    ("witness_received_pid", 0, 4, "identity:post_save"),
    ("witness_received_otid", 0, 4, "identity:post_save"),
    ("witness_final_result", 2, 1, "result:unchanged_after_commit"),
])
def test_identity_milestone_and_receipt_corruption_is_explained(producer, layout, field, value, width, reason):
    raw = put(trace(producer)[-1][2], layout, field, value, width)
    lua, _, obj, _ = reader(raw)
    snapshot, actual = obj.read(context(lua), 2)
    assert snapshot is None and actual == reason


@pytest.mark.parametrize("bits", [2, 5, 11])
def test_missing_predecessor_milestone_is_rejected(producer, layout, bits):
    raw = put(trace(producer)[-1][2], layout, "witness_milestones", bits, 4)
    lua, _, obj, _ = reader(raw)
    snapshot, reason = obj.read(context(lua), 2)
    assert snapshot is None and reason == "milestones:order"


def test_seen_bits_and_final_command_sequence_are_not_silently_rebound(producer):
    ready = next(raw for label, _, raw in trace(producer) if label == "ready")
    lua, module, obj, _ = reader(ready)
    ctx = context(lua)
    ctx["seen"] = 7
    snapshot, reason = obj.read(ctx, 2)
    assert snapshot is None and reason == "milestones:regressed"
    assert ctx["seen"] == 7 and module.classify(None, ctx["seen"])[0] == "UNCERTAIN"
    final = trace(producer)[-1][2]
    lua, _, obj, _ = reader(final)
    snapshot, reason = obj.read(context(lua), 3)
    assert snapshot is None and reason == "sequence:milestone"


def test_milestone_frames_are_diagnostics_not_a_time_gate(producer, layout):
    raw = bytearray(trace(producer)[-1][2])
    offset = layout["witness_offset"] + layout["witness_milestone_frame"]
    raw[offset:offset + 20] = b"\xff" * 20
    lua, module, obj, _ = reader(raw)
    snapshot, reason = obj.read(context(lua), 2)
    assert reason is None and snapshot["milestone_frame"][1] == 0xFFFFFFFF
    assert module.success(snapshot, 1, 2, 0xFEDCBA98, 0x87654321) == (True, None)


@pytest.mark.parametrize("field,value,width,reason", [
    ("mailbox_signature", 0, 4, "mailbox:signature"),
    ("mailbox_abi_version", 2, 2, "abi:mismatch"),
    ("mailbox_abi_version", 4, 2, "abi:mismatch"),
    ("mailbox_session_epoch", 8, 4, "identity:mailbox_epoch"),
    ("mailbox_producer_phase", 6, 4, "mailbox:phase"),
    ("mailbox_producer_phase", 3, 4, "phase:done"),
])
def test_mailbox_envelope_is_bound(producer, layout, field, value, width, reason):
    raw = put(trace(producer)[-1][2], layout, field, value, width, witness=False)
    lua, _, obj, _ = reader(raw)
    snapshot, actual = obj.read(context(lua), 2)
    assert snapshot is None and actual == reason


@pytest.mark.parametrize("fault", ["nil", "short", "hole", "invalid_byte", "throw", "copy_revision", "mailbox_change"])
def test_reader_faults_and_copy_races_never_return_bare_nil(producer, layout, fault):
    raw = trace(producer)[-1][2]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    epoch_reads = 0

    def u32(address):
        nonlocal epoch_reads
        value = int.from_bytes(raw[address - BASE:address - BASE + 4], "little")
        if address == BASE + layout["mailbox_session_epoch"]:
            epoch_reads += 1
            if fault == "mailbox_change" and epoch_reads == 2:
                return value + 1
        return value

    def read_bytes(address, n):
        if fault == "throw":
            raise RuntimeError("simulated unreadable memory")
        if fault == "nil":
            return None
        values = list(raw[address - BASE:address - BASE + n])
        if fault == "short":
            values.pop()
        if fault == "copy_revision":
            values[layout["witness_revision"]] ^= 2
        output = lua.table_from(values)
        if fault == "hole":
            output[12] = None
        if fault == "invalid_byte":
            output[12] = 256
        return output

    io = lua.table_from({"read_bytes": read_bytes, "read_u32": u32,
                         "read_u16": lambda a: int.from_bytes(raw[a - BASE:a - BASE + 2], "little")})
    obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3, "layout": lua.table_from(layout)}))
    assert why is None
    result = obj.read(context(lua), 2)
    assert isinstance(result, tuple) and len(result) == 2
    snapshot, reason = result
    want = "snapshot:revision" if fault == "copy_revision" else "mailbox:changed" if fault == "mailbox_change" else "read:error"
    assert snapshot is None and reason == want


def test_configuration_context_and_global_state_contract(producer, layout):
    raw = trace(producer)[-1][2]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    before = set(lua.globals().keys())
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    assert set(lua.globals().keys()) == before, "module must not create globals"
    io = lua.table_from({"read_bytes": lambda a, n: lua.table_from(list(raw[a - BASE:a - BASE + n]))})
    for change, reason in (({"abi": 4}, "abi:unsupported"), ({"base": -1}, "config:base"),
                           ({"base": 0xFFFFFFF0}, "config:base"),
                           ({"layout": lua.table_from(dict(layout, witness_revision=0))}, "config:layout")):
        cfg = lua.table_from({"base": BASE, "abi": 3} | change)
        obj, why = module.new(io, cfg)
        assert obj is None and why == reason
    obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3}))
    assert why is None
    for change, reason in (({"epoch": 0}, "context:identity"), ({"visit": 0}, "context:identity"),
                           ({"opaque": lua.table_from([0] * 16)}, "context:token"),
                           ({"prepare_seq": 0}, "context:sequence"), ({"seen": 32}, "context:seen")):
        ctx = context(lua)
        for key, value in change.items():
            ctx[key] = value
        snapshot, why = obj.read(ctx, 2)
        assert snapshot is None and why == reason
    assert obj.read(None, 2) == (None, "context:identity")
    assert module.classify(None, 0) == ("UNKNOWN", None)
    assert module.classify(None, 3) == ("UNCERTAIN", None)
    assert set(lua.globals().keys()) == before


def test_committed_requires_final_seq_equal_scene_seq_from_both_sides(producer):
    # Milestone 4 is bound to the caller's final_seq while success() binds milestones 2-5 to
    # scene_seq (C slink_trade_success_is_durable): a COMMITTED row is accepted only when equal.
    raw = trace(producer)[-1][2]
    lua, module, obj, _ = reader(raw)
    snapshot, reason = obj.read(context(lua), 2)
    assert snapshot is not None and reason is None and snapshot["classification"] == "COMMITTED"
    for wrong in (3, 1, None):
        lua, _, obj, _ = reader(raw)
        snapshot, reason = obj.read(context(lua), wrong)
        # The milestone-4 binding fires before the success predicate; success:sequence is
        # defence in depth that this reader cannot reach with a consistent context.
        assert snapshot is None and reason == "sequence:milestone", (wrong, reason)
    # The predicate side of the same rule, called directly on an accepted snapshot.
    lua, module, obj, _ = reader(raw)
    snapshot, _ = obj.read(context(lua), 2)
    assert module.success(snapshot, 1, 3, 0xFEDCBA98, 0x87654321) == (False, "success:scene_sequence")


def test_scene_failure_before_commit_is_accepted_and_uncertain_by_result_clause(producer, layout):
    rows = trace(producer, mode=6)
    assert [label for label, _, _ in rows][-1] == "scenefail"
    raw = rows[-1][2]
    base = layout["witness_offset"]
    assert int.from_bytes(raw[base + layout["witness_milestones"]:][:4], "little") == 17
    assert raw[base + layout["witness_final_result"]] == 3
    lua, module, obj, _ = reader(raw)
    snapshot, reason = obj.read(context(lua), 2)
    assert reason is None and snapshot["bits"] == 17 and snapshot["result"] == 3
    assert snapshot["phase"] == layout["phase_uncertain"] and snapshot["pending"] is False
    assert snapshot["classification"] == "UNCERTAIN"
    # Deciding clause is the result, not the commit marker: no commit bit, no prior commit seen.
    assert snapshot["bits"] & layout["commit_entered"] == 0
    assert module.classify(lua.table_from({"bits": 1, "result": 3}), 0) == ("UNCERTAIN", None)
    assert module.classify(lua.table_from({"bits": 1, "result": 0}), 0) == ("PENDING", None)
    # received_key refusal needs the commit marker, so it yields bits 19, never 17.
    foreign = trace(producer, mode=8)[-1][2]
    lua, _, obj, _ = reader(foreign)
    snapshot, reason = obj.read(context(lua), 2)
    assert reason is None and snapshot["bits"] == 19 and snapshot["classification"] == "UNCERTAIN"


def test_cancel_scene_is_accepted_and_unchanged_proving_commit_gate_is_not_vacuous(producer, layout):
    rows = trace(producer, mode=7)
    assert [label for label, _, _ in rows][-2:] == ["cancel", "cancelled"]
    base = layout["witness_offset"]
    cancel, final = rows[-2][2], rows[-1][2]
    assert int.from_bytes(final[base + layout["witness_milestones"]:][:4], "little") == 17
    assert final[base + layout["witness_final_result"]] == 2
    # Refused commit entry wrote nothing before the scene poll resolved it.
    assert cancel[base:] == rows[-3][2][base:]
    lua, module, obj, _ = reader(final)
    snapshot, reason = obj.read(context(lua), 2)
    assert reason is None and snapshot["classification"] == "UNCHANGED"
    assert snapshot["phase"] == layout["phase_done"]
    # The same real row with a commit-side bit added is refused by the (bits & 14) gate.
    forged = put(final, layout, "witness_milestones", 17 | 2, 4)
    at = base + layout["witness_milestone_seq"] + 2  # milestone 1 (COMMIT_ENTERED) needs its scene seq
    forged[at:at + 2] = (2).to_bytes(2, "little")
    lua, _, obj, _ = reader(forged)
    assert obj.read(context(lua), 2) == (None, "result:unchanged_after_commit")


def test_capabilities_are_deliberately_not_a_gate(producer):
    # The reader samples exactly signature/abi/epoch/phase. Capabilities (mailbox +0x40, flag
    # SLINK_CAP_DURABLE_TRADE=1) is the binder's admission gate, not this reader's.
    raw = trace(producer)[-1][2]
    assert int.from_bytes(raw[0x40:0x44], "little") & 1, "producer must advertise the durable-trade capability"
    for caps in (0, 0xFFFFFFFF):
        changed = bytearray(raw)
        changed[0x40:0x44] = caps.to_bytes(4, "little")
        lua, _, obj, _ = reader(changed)
        snapshot, reason = obj.read(context(lua), 2)
        assert reason is None and snapshot["classification"] == "COMMITTED", (caps, reason)


def test_non_callable_readers_are_refused_at_construction():
    # Userdata IS accepted on purpose: EmuHawk exposes memory.* as userdata and lupa wraps every
    # Python callable the same way, so the whole harness above exercises that form.
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    for bad in (5, "read", lua.table_from({}), True):
        for name in ("read_bytes", "read_u8", "read_u16", "read_u32"):
            io = lua.table_from({name: bad, "read_u8": lambda a: 0} if name != "read_u8" else {name: bad})
            obj, why = module.new(io, lua.table_from({"base": BASE, "abi": 3}))
            assert obj is None and why == "config:reader", (bad, name, why)
