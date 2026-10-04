"""Host-C falsifiers for the Gen 4 trade POLICY (patch/src/nds/gen4/trade.h,
trade_policy.h) -- card C5. Spec: docs/gen4/companion/C5_TRADE_SPEC.md.

The REAL headers are compiled with -std=c11 -Wall -Wextra -Werror and driven through a
fake Gen 4 engine, so every claim below is a claim about the shipped header and not about
a test double of it. No emulator, no ROM, no game header.

Covered falsifiers (spec section given per test):
  F1  §3.2 / §5    the record handed to the scene is byte-identical to the host stage,
                   even when the engine's decode primitives scribble in place
  F2  §4.3        a bad stage leaves the party byte-identical
  F3  §4.1/§5     17 stage-refusal shapes, each SLINK_TRADE_UNCHANGED with no mutation
  F4  §3.3 / §5   an out-of-party or empty-party slot is REFUSED, never asserted
  F7  §1-30       a foreign opcode (sound/panel) leaves the trade alone while the async
                   save watchdog keeps ticking
  F8  §3.4 / §5   received_key reads the PARTY SLOT through the decoder; the mutant that
                   reads the staging buffer stays RED
  §3.3            one in-flight trade; WITHDRAW/STATUS semantics
  §3.5 / §7 Q2    the save-timeout watchdog: PENDING past the bound is FAIL/UNCERTAIN

Every green test is re-run against a seeded defect (MUTANTS below) and must go red, so no
test here measures nothing.

Run: pytest tests/unit/test_gen4_trade_policy.py -v
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "patch/src/nds/common"
GEN4 = ROOT / "patch/src/nds/gen4"
CC_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]

TP = "trade_policy.h"
TRADE_H = "trade.h"
COMMON_TP = "trade_producer.h"


# --------------------------------------------------------------------------- toolchain

def _find_gcc() -> str | None:
    """env SLINK_HOST_GCC, PATH, then <repo common dir parent>/.cache/build-tools (worktree safe)."""
    for cand in (os.environ.get("SLINK_HOST_GCC"), shutil.which("gcc")):
        if cand:
            return cand
    bases = [ROOT]
    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
                         capture_output=True, text=True, timeout=30)
    if git.returncode == 0 and git.stdout.strip():
        bases.append((ROOT / git.stdout.strip()).resolve().parent)
    for base in bases:
        tools = base / ".cache" / "build-tools"
        for pattern in ("*/bin/gcc.exe", "*/*/bin/gcc.exe"):
            for gcc in sorted(tools.glob(pattern)):
                if (gcc.parent.parent / "libexec").is_dir():  # a bare bin/ shim has no cc1
                    return str(gcc)
    return None


def _gcc() -> str:
    gcc = _find_gcc()
    if not gcc:
        reason = ("no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
                  ".cache/build-tools/*/bin/gcc.exe); Gen 4 trade-policy falsifiers did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def test_host_c_compiler_is_discoverable():
    """All-skipped must be distinguishable from all-passed: SLINK_REQUIRE_HOST_CC=1 fails instead."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _build(tmp, name, source, includes, defines=()):
    src = tmp / f"{name}.c"
    src.write_text(source, encoding="utf-8")
    exe = tmp / f"{name}.exe"
    cmd = [_gcc(), *CC_FLAGS, *defines]
    for inc in includes:
        cmd += ["-I", str(inc)]
    cmd += [str(src), "-o", str(exe)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return exe


def _run(exe, *args):
    done = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stdout + done.stderr + f" exit={done.returncode}"
    return done.stdout


# --------------------------------------------------------------------------- the fake Gen 4 engine

HARNESS_C = r'''/* Card C5 host-C harness: the REAL trade.h / trade_policy.h over a fake Gen 4 engine. */
#include "trade.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)

#define OLD_PID 0x11223344u
#define OLD_OT  0x55667788u
#define NEW_PID 0xA1B2C3D4u
#define NEW_OT  0x8BADF00Du
#define STAGE_LEN 0xECu                 /* slink_binding_gen4_pk4.party_len; trade_stage_len is 0 */
#define SCRIBBLE 0x40u                  /* inside the data blocks: never PID, OT or the checksum word */

/* ---- the policy under test and the ABI objects it is pointed at ---- */
static SlinkGen4TradePolicy pol;
static volatile SlinkMailboxV2 m;
static volatile SlinkTradeWitnessV2 w;
static volatile SlinkRecordStageV1 stage;
static SlinkGen4TradeSeam seam;

/* ---- the fake game's party ---- */
static uint8_t party[6][SLINK_MAX_RECORD];
static uint8_t party_snap[6][SLINK_MAX_RECORD];
static uint8_t party0_snap[SLINK_MAX_RECORD];
static uint8_t stage_rec[SLINK_MAX_RECORD];
static uint8_t handed[SLINK_MAX_RECORD];
static uint16_t handed_len;
static const uint8_t *handed_ptr;
static int handed_misaligned;

/* ---- knobs ---- */
static int party_n, slot_arg, chosen, safe_flag, pre_result, scene_result;
static int begin_ok, scene_start_ok, hostile_decode, shrink_on_verify, tamper_after_commit;
static int step, save_result;
static unsigned verify_calls, identity_calls, record_calls, save_polls;
static unsigned scene_starts, commits, asserted;
static uint32_t clock_c;

static uint8_t *unv(volatile uint8_t *p) { return (uint8_t *)(void *)p; }
static const SlinkTradeWitnessV2 *cw(void) { return (const SlinkTradeWitnessV2 *)(const void *)(uintptr_t)&w; }

/* The record encoding the fake decoder implements: pid plaintext at +0, otid at logical
 * +0x0C stored XOR 0xA5 per byte, integrity word 0x5A at +6 (mirrors CalcMonChecksum ==
 * box.checksum). */
static void enc(uint8_t *r, uint32_t pid, uint32_t ot, unsigned seed)
{
    unsigned i;
    memset(r, 0, SLINK_MAX_RECORD);
    for (i = 0; i < SLINK_MAX_RECORD; i++) r[i] = (uint8_t)(i * 7u + 3u + seed);
    for (i = 0; i < 4u; i++) {
        r[i] = (uint8_t)(pid >> (8u * i));
        r[0x0Cu + i] = (uint8_t)((ot >> (8u * i)) ^ 0xA5u);
    }
    r[6] = 0x5A;
}

static void dec(const uint8_t *r, uint32_t *pid, uint32_t *ot)
{
    unsigned k;
    *pid = 0u; *ot = 0u;
    for (k = 0; k < 4u; k++) {
        *pid |= (uint32_t)r[k] << (8u * k);
        *ot |= (uint32_t)(r[0x0Cu + k] ^ 0xA5u) << (8u * k);
    }
}

/* ---- the seam ---- */
static int f_party_count(void *ctx) { (void)ctx; return party_n; }

static int f_party_slot_identity(void *ctx, unsigned slot, SlinkIdentity *out)
{
    uint32_t pid, ot;
    (void)ctx;
    if (slot >= 6u || (int)slot >= party_n) return 0;
    identity_calls++;
    dec(party[slot], &pid, &ot);
    out->pid = pid;
    out->otid = ot;
    return 1;
}

static int f_party_slot_record(void *ctx, unsigned slot, const uint8_t **bytes, uint16_t *len)
{
    (void)ctx;
    record_calls++;
    if (slot >= 6u || (int)slot >= party_n) return 0;
    *bytes = party[slot];
    *len = STAGE_LEN;
    return 1;
}

static int f_script_chosen(void *ctx, unsigned *out) { (void)ctx; *out = (unsigned)chosen; return 1; }

/* Models PARTY_ASSERT_SLOT: src/party.c:9-12 with asserts live (config.mk:36-37). An
 * out-of-range slot is a cartridge HALT, so the fake records the abort and writes nothing. */
static int f_commit(void *ctx, unsigned slot, const uint8_t *rec, uint16_t len)
{
    (void)ctx;
    if (slot >= 6u || (int)slot >= party_n) { asserted = 1; return 0; }
    if (rec == 0 || len != STAGE_LEN) return 0;
    memcpy(party[slot], rec, len);
    commits++;
    if (tamper_after_commit) enc(party[slot], NEW_PID ^ 0x01010101u, NEW_OT ^ 1u, 9u);
    return 1;
}

static int f_safe(void *ctx) { (void)ctx; return safe_flag; }
static int f_pre_start(void *ctx) { (void)ctx; return 1; }
static int f_pre_poll(void *ctx) { (void)ctx; return pre_result; }
static int f_scene_poll(void *ctx) { (void)ctx; return scene_result; }
static int f_post_begin(void *ctx) { (void)ctx; return begin_ok; }
static int f_post_poll(void *ctx) { (void)ctx; save_polls++; return save_result; }
static uint32_t f_frame(void *ctx) { (void)ctx; return clock_c; }

static int f_scene_start(void *ctx, unsigned slot, const uint8_t *rec, uint16_t len)
{
    (void)ctx; (void)slot;
    scene_starts++;
    if (((uintptr_t)rec & 3u) != 0u) handed_misaligned = 1;
    handed_ptr = rec;
    handed_len = len;
    memset(handed, 0xCD, sizeof handed);
    memcpy(handed, rec, len);
    return scene_start_ok;
}

/* The engine's own decode primitives. MonDecryptSegment mutates its argument in place, so
 * hostile_decode models exactly the leak the policy's scratch copy exists to stop. */
static int f_decode(void *ctx, const uint8_t *r, uint16_t n, uint16_t off, uint32_t *out)
{
    uint8_t *live;
    unsigned k;
    (void)ctx;
    if (hostile_decode) { live = (uint8_t *)(void *)r; live[SCRIBBLE] ^= 0xFFu; }
    if ((unsigned)off + 4u > (unsigned)n) return 0;
    *out = 0u;
    for (k = 0; k < 4u; k++) *out |= (uint32_t)(r[off + k] ^ 0xA5u) << (8u * k);
    return 1;
}

static int f_verify(void *ctx, const uint8_t *r, uint16_t n)
{
    uint8_t *live;
    (void)ctx;
    verify_calls++;
    if (hostile_decode) { live = (uint8_t *)(void *)r; live[SCRIBBLE] ^= 0xFFu; }
    if (shrink_on_verify && party_n > 2) party_n = 2;
    if (n < 8u) return 0;
    return r[6] == 0x5A;
}

/* ---- plumbing ---- */
static void svc(void)
{
    clock_c += (uint32_t)step;
    Slink_Gen4TradePolicy_Service(&pol, &m);
}
static void word(volatile uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static void send_prepare(uint32_t epoch, uint16_t seq)
{
    m.session_epoch = epoch; m.seq = seq; m.opcode = SLINK_OP_TRADE_PREPARE;
    m.args[0] = (uint8_t)slot_arg; m.args[1] = 0u;
    word(m.args + 4, OLD_PID); word(m.args + 8, OLD_OT); word(m.args + 12, 8u);
    m.args[16] = 9u;
}
static void scene(uint16_t seq)
{
    m.seq = seq; m.opcode = SLINK_OP_TRADE_SCENE; m.args[0] = (uint8_t)slot_arg;
    svc();
}

static void reset(void)
{
    memset(&pol, 0, sizeof pol);
    memset((void *)(uintptr_t)&m, 0, sizeof m);
    memset((void *)(uintptr_t)&w, 0, sizeof w);
    memset((void *)(uintptr_t)&stage, 0xEE, sizeof stage);
    memset(&seam, 0, sizeof seam);
    memset(party, 0, sizeof party);
    memset(handed, 0, sizeof handed);
    party_n = 1; slot_arg = 0; chosen = 0; safe_flag = 1;
    pre_result = 0; scene_result = 0; begin_ok = 1; scene_start_ok = 1;
    hostile_decode = 0; shrink_on_verify = 0; tamper_after_commit = 0;
    verify_calls = identity_calls = record_calls = save_polls = 0;
    scene_starts = commits = asserted = 0;
    handed_len = 0; handed_ptr = 0; handed_misaligned = 0;
    clock_c = 0; step = 1; save_result = SLINK_SAVEPOLL_OK;
    enc(party[0], OLD_PID, OLD_OT, 0u);
    enc(stage_rec, NEW_PID, NEW_OT, 1u);
    memcpy(party_snap, party, sizeof party);
    memcpy(party0_snap, party[0], SLINK_MAX_RECORD);
    stage.layout_version = SLINK_NDS_STAGE_LAYOUT;
    stage.binding_id = SLINK_BIND_GEN4_PK4;
    stage.generation = 4u;
    stage.flags = (uint8_t)SLINK_STAGE_RAW_ENCRYPTED;
    stage.stage_len = (uint16_t)STAGE_LEN;
    stage.claimed_pid = NEW_PID; stage.claimed_otid = NEW_OT;
    memcpy(unv(stage.record), stage_rec, STAGE_LEN);
    seam.party_count = f_party_count;
    seam.party_slot_identity = f_party_slot_identity;
    seam.party_slot_record = f_party_slot_record;
    seam.script_chosen_slot = f_script_chosen;
    seam.commit_party_slot = f_commit;
    seam.safe_field = f_safe;
    seam.start_pre_save = f_pre_start;
    seam.poll_pre_save = f_pre_poll;
    seam.scene_start = f_scene_start;
    seam.poll_scene = f_scene_poll;
    seam.post_save_begin = f_post_begin; seam.post_save_poll = f_post_poll;
    seam.decode_read_u32 = f_decode;
    seam.verify = f_verify;
    seam.frame = f_frame;
    if (!Slink_Gen4TradePolicy_Init(&pol, &seam, &w, &stage, 1000000u)) {
        printf("FAIL line %d: Slink_Gen4TradePolicy_Init\n", __LINE__);
        exit(1);
    }
}

static int prep(void)
{
    send_prepare(7, 1);
    svc();
    CHECK(m.producer_phase == SLINK_PHASE_PRE_SAVE);
    CHECK((w.visit_flags & SLINK_VISIT_ACCEPTED) != 0);
    CHECK(w.milestones == 0);
    pre_result = 2; svc();                       /* YesNo = yes: consent, still waiting */
    CHECK((w.visit_flags & SLINK_PRE_SAVE_CONSENT) != 0);
    CHECK(m.producer_phase == SLINK_PHASE_PRE_SAVE);
    pre_result = 1; svc();                       /* the adapter's consent -> ready step */
    CHECK(m.producer_phase == SLINK_PHASE_READY);
    CHECK(m.status == SLINK_ST_OK && m.ack_seq == 1 && m.opcode == 0);
    CHECK((w.milestones & (1u << SLINK_PRE_SAVE_OK)) != 0);
    return 0;
}

/* Every stage refusal must land here: nothing touched, and the durable predicate fails. */
static int refused_unchanged(void)
{
    CHECK(scene_starts == 0);
    CHECK(commits == 0 && asserted == 0);
    CHECK(w.final_result == SLINK_TRADE_UNCHANGED);
    CHECK((w.milestones & (1u << SLINK_COMMIT_ENTERED)) == 0);
    CHECK(w.milestones == ((1u << SLINK_PRE_SAVE_OK) | (1u << SLINK_FINAL_RESULT)));
    CHECK(m.status == SLINK_ST_FAIL);
    CHECK(m.producer_phase == SLINK_PHASE_DONE);
    CHECK(!slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    CHECK(memcmp(party, party_snap, sizeof party) == 0);
    return 0;
}

/* ------------------------------------------------------------------ scenarios */

static int sc_happy(void)
{
    unsigned i;
    reset();
    if (prep()) return 1;
    scene(2);
    /* F1: the record the scene sees is the host's at-rest bytes, byte for byte. */
    CHECK(scene_starts == 1 && !handed_misaligned);
    CHECK(handed_len == STAGE_LEN);
    CHECK(memcmp(handed, stage_rec, STAGE_LEN) == 0);
    CHECK(memcmp(pol.producer.incoming, stage_rec, STAGE_LEN) == 0);
    CHECK(memcmp(pol.producer.scratch, stage_rec, STAGE_LEN) == 0);
    CHECK(memcmp(unv(stage.record), stage_rec, STAGE_LEN) == 0);
    /* PK4 sets SLINK_RB_COMMIT_MUTATES_INPUT, so the engine gets the scratch, never the
     * staging buffer it could scribble on (record_binding.h:167-171; C5_TRADE_SPEC.md:204). */
    CHECK(handed_ptr == (const uint8_t *)pol.producer.scratch);
    CHECK(handed_ptr != (const uint8_t *)pol.producer.incoming);
    for (i = STAGE_LEN; i < (unsigned)SLINK_MAX_RECORD; i++) CHECK(pol.producer.incoming[i] == 0u);
    CHECK(pol.producer.incoming_len == STAGE_LEN);
    CHECK(pol.pending_valid == 1 && pol.pending_slot == 0);
    CHECK(m.status == SLINK_ST_BUSY && m.producer_phase == SLINK_PHASE_SCENE);
    /* §3.3 order: the marker first, and it mutates nothing. */
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    CHECK((w.milestones & (1u << SLINK_COMMIT_ENTERED)) != 0);
    CHECK(commits == 0);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 1);
    CHECK(commits == 1 && asserted == 0);
    CHECK(memcmp(party[0], stage_rec, STAGE_LEN) == 0);
    CHECK(pol.pending_valid == 0);
    /* field returns; the native save is asynchronous and only the poll resolves it */
    scene_result = 1; save_result = SLINK_SAVEPOLL_PENDING;
    m.opcode = 0;
    svc();
    CHECK(w.save_status == SLINK_SAVE_PENDING);
    CHECK((w.milestones & (1u << SLINK_POST_SAVE_OK)) == 0);
    CHECK(w.final_result == SLINK_TRADE_PENDING);
    CHECK(!slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    save_result = SLINK_SAVEPOLL_OK;
    svc();
    CHECK(w.final_result == SLINK_TRADE_COMMITTED);
    CHECK(w.save_status == SLINK_SAVE_OK);
    CHECK((w.milestones & SLINK_SUCCESS_MILESTONES) == SLINK_SUCCESS_MILESTONES);
    CHECK(m.status == SLINK_ST_OK && m.ack_seq == 2);
    CHECK(m.producer_phase == SLINK_PHASE_DONE);
    CHECK(slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    CHECK(w.received_pid == NEW_PID && w.received_otid == NEW_OT);
    /* the readback came from the PARTY SLOT: exactly one party_slot_record call, no more */
    CHECK(record_calls == 1);
    CHECK(verify_calls >= 1u && identity_calls >= 1u);
    return 0;
}

/* F3 (spec :395-397) + §4.2.2 fail-closed. One shape per var. */
static int sc_refuse(int var)
{
    reset();
    if (prep()) return 1;
    switch (var) {
    case 0: stage.stage_len = 0xEBu; break;                       /* (a) truncated */
    case 1: stage.stage_len = 0x88u; break;                       /* (a) the stored/box prefix */
    case 2: stage.stage_len = 0xEDu; break;                       /* (a) oversize by one */
    case 3: stage.binding_id = 5u; break;                         /* (b) */
    case 4: stage.generation = 3u; break;                         /* (c) */
    case 5: stage.layout_version = 2u; break;                     /* (f) */
    case 6: stage.flags = (uint8_t)(SLINK_STAGE_RAW_ENCRYPTED | 0x02u); break; /* (d) */
    case 7: stage.flags = 0u; break;                              /* (e) RAW_ENCRYPTED cleared */
    case 8: stage.claimed_otid ^= 1u; break;                      /* (g) claim altered */
    case 9: stage.claimed_pid ^= 1u; break;                       /* (g) claim altered */
    case 10: unv(stage.record)[0] ^= 1u; break;                   /* record PID != claim */
    case 11: unv(stage.record)[0x0Cu] ^= 1u; break;               /* decoded OT != claim */
    case 12: seam.decode_read_u32 = 0; break;                    /* no decoder: fail closed */
    case 13: seam.verify = 0; break;                              /* no verify: fail closed */
    case 14: unv(stage.record)[6] = 0x5Bu; break;                 /* (h) CHECKSUM disagrees */
    case 15: stage.stage_len = 0xFFFFu; break;
    case 16: stage.stage_len = (uint16_t)SLINK_MAX_RECORD; break;
    default: return 2;
    }
    scene(2);
    return refused_unchanged();
}

/* F1: the engine's decode primitives mutate their argument in place (C5_TRADE_SPEC.md:242). */
static int sc_hostile(void)
{
    reset();
    if (prep()) return 1;
    hostile_decode = 1;
    scene(2);
    CHECK(scene_starts == 1);
    CHECK(memcmp(handed, stage_rec, STAGE_LEN) == 0);
    CHECK(memcmp(pol.producer.incoming, stage_rec, STAGE_LEN) == 0);
    CHECK(memcmp(unv(stage.record), stage_rec, STAGE_LEN) == 0);
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 1);
    scene_result = 1; save_result = SLINK_SAVEPOLL_OK;
    m.opcode = 0;
    svc();
    /* the readback path is guarded too: decoding never touched the party record */
    CHECK(record_calls == 1);
    CHECK(memcmp(party[0], stage_rec, STAGE_LEN) == 0);
    CHECK(w.final_result == SLINK_TRADE_COMMITTED);
    CHECK(w.received_pid == NEW_PID && w.received_otid == NEW_OT);
    return 0;
}

/* F8 (spec :412-413): the readback is an OBSERVATION of the party slot. */
static int sc_received_from_party(void)
{
    reset();
    if (prep()) return 1;
    tamper_after_commit = 1;                 /* the game put something else in that slot */
    scene(2);
    CHECK(scene_starts == 1);
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 1);
    CHECK(commits == 1 && w.received_pid == 0u);
    scene_result = 1; save_result = SLINK_SAVEPOLL_OK;
    m.opcode = 0;
    svc();
    CHECK(record_calls == 1);
    /* the slot's OWN bytes were decoded (not the staging buffer): the producer keeps what it observed in
     * received_id, and publishes it to the witness only on POST_SAVE_OK, which a mismatch never reaches. */
    CHECK(pol.producer.received_id.pid == (NEW_PID ^ 0x01010101u));
    CHECK(pol.producer.received_id.otid == (NEW_OT ^ 1u));
    CHECK(pol.producer.received_id.pid != NEW_PID);
    CHECK(w.received_pid == 0u && w.received_otid == 0u);
    CHECK(w.final_result == SLINK_TRADE_UNCERTAIN);
    CHECK(m.status == SLINK_ST_FAIL && m.reason == SLINK_REASON_UNCERTAIN);
    CHECK(m.producer_phase == SLINK_PHASE_UNCERTAIN);
    CHECK((w.milestones & (1u << SLINK_POST_SAVE_OK)) == 0);
    CHECK(!slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    return 0;
}

static int sc_one_in_flight(void)
{
    reset();
    send_prepare(7, 1);
    svc();
    CHECK(m.producer_phase == SLINK_PHASE_PRE_SAVE && m.status == SLINK_ST_BUSY);
    m.seq = 2; m.opcode = SLINK_OP_TRADE_PREPARE; svc();
    CHECK(m.status == SLINK_ST_FAIL && m.reason == SLINK_REASON_IDENTITY);
    CHECK(m.producer_phase == SLINK_PHASE_PRE_SAVE && scene_starts == 0);
    pre_result = 1; m.seq = 1; m.opcode = 0; svc();
    CHECK(m.producer_phase == SLINK_PHASE_READY);
    m.seq = 3; m.opcode = SLINK_OP_TRADE_STATUS; svc();
    CHECK(m.status == SLINK_ST_OK && m.producer_phase == SLINK_PHASE_READY);
    m.seq = 4; m.opcode = SLINK_OP_TRADE_PREPARE; svc();
    CHECK(m.status == SLINK_ST_FAIL && m.producer_phase == SLINK_PHASE_READY);
    scene(2);
    CHECK(m.producer_phase == SLINK_PHASE_SCENE);
    m.seq = 5; m.opcode = SLINK_OP_TRADE_SCENE; svc();
    CHECK(scene_starts == 1 && m.producer_phase == SLINK_PHASE_SCENE);
    m.seq = 6; m.opcode = SLINK_OP_TRADE_WITHDRAW; svc();
    CHECK(m.status == SLINK_ST_FAIL && m.reason == SLINK_REASON_WITHDRAW_TOO_LATE);
    CHECK(scene_starts == 1 && commits == 0);
    return 0;
}

/* §3.5: PENDING past save_timeout_frames is FAIL, so UNCERTAIN stays reachable. */
static int sc_save_timeout(void)
{
    unsigned commits0, scene_starts0;
    SlinkTradeWitnessV2 snap;
    reset();
    if (prep()) return 1;
    pol.engine.save_timeout_frames = 50u;
    scene(2);
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 1);
    scene_result = 1; save_result = SLINK_SAVEPOLL_PENDING;
    m.opcode = 0;
    svc();
    CHECK(w.save_status == SLINK_SAVE_PENDING);
    CHECK((w.milestones & (1u << SLINK_POST_SAVE_OK)) == 0);
    clock_c += 49u; svc();                      /* elapsed 50: still exactly at the bound */
    CHECK(w.save_status == SLINK_SAVE_PENDING && w.final_result == SLINK_TRADE_PENDING);
    clock_c += 1u; svc();                       /* elapsed 51: PENDING becomes FAIL */
    CHECK(w.final_result == SLINK_TRADE_UNCERTAIN && w.save_status == SLINK_SAVE_FAILED);
    CHECK((w.milestones & (1u << SLINK_POST_SAVE_OK)) == 0);
    CHECK(m.status == SLINK_ST_FAIL && m.reason == SLINK_REASON_UNCERTAIN);
    CHECK(m.producer_phase == SLINK_PHASE_UNCERTAIN);
    CHECK(!slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    /* sticky: no second scene or save, no new visit */
    commits0 = commits;
    scene_starts0 = scene_starts;
    memcpy(&snap, (void *)(uintptr_t)&w, sizeof snap);
    m.seq = 9; m.opcode = SLINK_OP_TRADE_SCENE; svc();
    CHECK(commits == commits0 && scene_starts == scene_starts0);
    CHECK(snap.milestones == w.milestones && snap.final_result == w.final_result);
    send_prepare(9, 10); svc();
    CHECK(m.producer_phase == SLINK_PHASE_UNCERTAIN && commits == commits0);
    return 0;
}

/* §1-30 / F7: a foreign opcode is another producer's; the watchdog still ticks. */
static int sc_foreign(void)
{
    uint16_t ack, reason, status;
    unsigned polls0;
    reset();
    if (prep()) return 1;
    scene(2);
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 1);
    scene_result = 1; save_result = SLINK_SAVEPOLL_PENDING;
    m.opcode = 0;
    svc();
    CHECK(w.save_status == SLINK_SAVE_PENDING);
    ack = m.ack_seq; reason = m.reason; status = m.status;
    polls0 = save_polls;
    m.seq = 40; m.opcode = SLINK_OP_PLAY_SE; svc();
    CHECK(save_polls == polls0 + 1u);
    CHECK(m.opcode == SLINK_OP_PLAY_SE && m.seq == 40);
    CHECK(m.ack_seq == ack && m.status == status && m.reason == reason);
    CHECK(m.producer_phase == SLINK_PHASE_SCENE);
    m.seq = 41; m.opcode = SLINK_OP_SHOW_INFO; svc();
    CHECK(save_polls == polls0 + 2u);
    CHECK(m.opcode == SLINK_OP_SHOW_INFO && m.seq == 41);
    save_result = SLINK_SAVEPOLL_OK;
    svc();
    CHECK(w.final_result == SLINK_TRADE_COMMITTED);
    CHECK(w.save_status == SLINK_SAVE_OK);
    CHECK(slink_trade_success_is_durable(cw(), 1, 2, NEW_PID, NEW_OT));
    /* Never acked someone else's opcode: the held request keeps its seq and opcode, and
     * tp_ack's own sequence guard (trade_producer.h:97) therefore also suppresses the
     * trade's own SCENE ack while it is held. The host re-sends SCENE; nothing is lost. */
    CHECK(m.opcode == SLINK_OP_SHOW_INFO && m.seq == 41);
    CHECK(m.ack_seq == ack && m.status == status && m.reason == reason);
    return 0;
}

/* F4: a slot that stops being inside the party DURING the scene visit is refused. */
static int sc_refuse_shrunk(void)
{
    unsigned i;
    reset();
    party_n = 6;
    for (i = 0; i < 6u; i++) enc(party[i], 0x1000u + i, 0x2000u + i, 0u);
    enc(party[5], OLD_PID, OLD_OT, 0u);
    slot_arg = 5; chosen = 5;
    memcpy(party_snap, party, sizeof party);
    if (prep()) return 1;
    shrink_on_verify = 1;                    /* the party empties mid-visit */
    scene(2);
    CHECK(party_n == 2);
    CHECK(w.final_result == SLINK_TRADE_UNCHANGED);
    CHECK(scene_starts == 0 && commits == 0 && asserted == 0);
    CHECK(memcmp(party, party_snap, sizeof party) == 0);
    return 0;
}

/* F4: an empty party has no live slot at all -- never a locate hit, never an assert. */
static int sc_refuse_empty(void)
{
    reset();
    party_n = 0;
    send_prepare(7, 1);
    svc();
    CHECK(m.status == SLINK_ST_FAIL && m.reason == 2);
    CHECK(m.producer_phase == SLINK_PHASE_IDLE);
    CHECK(w.milestones == 0 && w.session_epoch == 0u);
    CHECK(scene_starts == 0 && commits == 0 && asserted == 0);
    /* and the write site refuses an emptied party even with a legal stage and a marker */
    reset();
    if (prep()) return 1;
    scene(2);
    CHECK(scene_starts == 1);
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);
    party_n = 0;
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 0);
    CHECK(commits == 0 && asserted == 0);
    CHECK(memcmp(party[0], party0_snap, STAGE_LEN) == 0);
    return 0;
}

/* §3.3: the copy is gated on the commit marker, so no ScrCmd ordering slip writes early. */
static int sc_commit_without_marker(void)
{
    reset();
    if (prep()) return 1;
    scene(2);
    CHECK(scene_starts == 1);
    CHECK((w.milestones & (1u << SLINK_COMMIT_ENTERED)) == 0);
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 0);
    CHECK(commits == 0 && asserted == 0);
    CHECK(memcmp(party[0], party0_snap, STAGE_LEN) == 0);
    return 0;
}

/* §3.3 step 1: the slot the SCRIPT variable carries is the only slot that may be written. */
static int sc_chosen_disagrees(void)
{
    reset();
    party_n = 2;
    enc(party[1], 0x777u, 0x888u, 2u);
    chosen = 1;                              /* the script names a different, live slot */
    if (prep()) return 1;
    memcpy(party_snap, party, sizeof party);
    scene(2);
    CHECK(w.final_result == SLINK_TRADE_UNCHANGED);
    CHECK(scene_starts == 0 && commits == 0 && asserted == 0);
    CHECK(memcmp(party, party_snap, sizeof party) == 0);
    return 0;
}

/* An unarmed policy must never stand between the game and an ordinary NPC trade. */
static int sc_vanilla(void)
{
    SlinkGen4TradePolicy empty;
    memset(&empty, 0, sizeof empty);
    CHECK(Slink_Gen4Trade_CommitEntered(&empty, 0) == 1);
    CHECK(Slink_Gen4Trade_Commit(&empty, 0) == 1);
    reset();
    CHECK(Slink_Gen4Trade_CommitEntered(&pol, 0) == 1);    /* armed, phase IDLE: not ours */
    CHECK(Slink_Gen4Trade_Commit(&pol, 0) == 0);            /* but nothing is armed to write */
    CHECK(commits == 0 && asserted == 0);
    return 0;
}

/* Init refuses an unusable configuration; a half-built seam refuses rather than crashes. */
static int sc_init(void)
{
    SlinkGen4TradePolicy p;
    SlinkGen4TradeSeam s;
    memset(&p, 0, sizeof p);
    memset(&s, 0, sizeof s);
    s.frame = f_frame;
    CHECK(Slink_Gen4TradePolicy_Init(&p, 0, &w, &stage, 100u) == 0);
    CHECK(Slink_Gen4TradePolicy_Init(&p, &s, 0, &stage, 100u) == 0);
    CHECK(Slink_Gen4TradePolicy_Init(&p, &s, &w, 0, 100u) == 0);
    CHECK(Slink_Gen4TradePolicy_Init(&p, &s, &w, &stage, 0u) == 0);  /* watchdog bound mandatory */
    s.frame = 0;
    CHECK(Slink_Gen4TradePolicy_Init(&p, &s, &w, &stage, 100u) == 0);
    reset();
    /* every game primitive missing: PREPARE cannot locate, so nothing arms */
    seam.party_count = 0; seam.party_slot_identity = 0; seam.party_slot_record = 0;
    seam.script_chosen_slot = 0; seam.commit_party_slot = 0; seam.safe_field = 0;
    seam.start_pre_save = 0; seam.poll_pre_save = 0; seam.scene_start = 0;
    seam.poll_scene = 0; seam.post_save_begin = 0; seam.decode_read_u32 = 0;
    seam.verify = 0;
    CHECK(Slink_Gen4TradePolicy_Init(&pol, &seam, &w, &stage, 100u) == 1);
    send_prepare(7, 1);
    svc();
    CHECK(m.status == SLINK_ST_FAIL && m.producer_phase == SLINK_PHASE_IDLE);
    CHECK(scene_starts == 0 && commits == 0 && asserted == 0);
    /* and an unarmed/absent policy simply does nothing per visit */
    memset(&pol, 0, sizeof pol);
    svc();
    CHECK(m.producer_phase == 0);
    return 0;
}

int main(int argc, char **argv)
{
    int sc = argc > 1 ? atoi(argv[1]) : 0;
    int var = argc > 2 ? atoi(argv[2]) : 0;
    switch (sc) {
    case 1: return sc_happy();
    case 2: return sc_refuse(var);
    case 3: return sc_hostile();
    case 4: return sc_received_from_party();
    case 5: return sc_one_in_flight();
    case 6: return sc_save_timeout();
    case 7: return sc_foreign();
    case 8: return sc_refuse_shrunk();
    case 9: return sc_refuse_empty();
    case 10: return sc_commit_without_marker();
    case 11: return sc_chosen_disagrees();
    case 12: return sc_vanilla();
    case 13: return sc_init();
    default: return 99;
    }
}
'''


# One shape per entry; the spec line is the C5_TRADE_SPEC.md §5 F3 bullet it comes from.
REFUSAL_SHAPES = (
    ("stage-len-truncated-a", 0),
    ("stage-len-stored-prefix-a", 1),
    ("stage-len-oversize-a", 2),
    ("binding-id-not-gen4-b", 3),
    ("generation-not-4-c", 4),
    ("layout-version-wrong-f", 5),
    ("unknown-stage-flag-d", 6),
    ("raw-encrypted-cleared-e", 7),
    ("claimed-otid-altered-g", 8),
    ("claimed-pid-altered-g", 9),
    ("record-pid-not-claim-g", 10),
    ("record-ot-not-claim-g", 11),
    ("no-decoder-fails-closed", 12),
    ("no-verify-fails-closed", 13),
    ("engine-checksum-disagrees-h", 14),
    ("stage-len-ffff-a", 15),
    ("stage-len-max-record-a", 16),
)

SCENARIOS = (
    [("happy", 1, 0)]
    + [(name, 2, var) for name, var in REFUSAL_SHAPES]
    + [
        ("hostile-in-place-decoder", 3, 0),
        ("received-key-from-party-slot", 4, 0),
        ("one-in-flight", 5, 0),
        ("save-timeout-watchdog", 6, 0),
        ("foreign-opcode-unowned", 7, 0),
        ("party-shrinks-during-scene", 8, 0),
        ("empty-party-refused", 9, 0),
        ("commit-requires-marker", 10, 0),
        ("script-chosen-slot-wins", 11, 0),
        ("vanilla-trade-unaffected", 12, 0),
        ("init-and-empty-seam", 13, 0),
    ]
)


@pytest.fixture(scope="module")
def policy_exe(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen4-trade-policy")
    return _build(tmp, "gen4_trade_policy", HARNESS_C, includes=(COMMON, GEN4))


@pytest.mark.parametrize("name,sc,var", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_gen4_trade_policy_scenarios(policy_exe, name, sc, var):
    _run(policy_exe, sc, var)


# --------------------------------------------------------------------------- mutants
# Every green scenario above is re-run against a seeded defect. A mutant that stays green
# means the corresponding test measures nothing. The shared-header edits use `0 &&` so the
# mutant still COMPILES: an uncompilable mutant would fail the build assertion instead of
# proving the scenario goes red.

MUTANTS = {
    # F8: a readback derived from the staged buffer agrees with incoming_id by
    # construction, so the identity chain is a tautology.
    "received-key-from-staging-decoder": (
        (4, 0), [(TP,
                  "    if (!s->party_slot_record) return 0;\n"
                  "    if (!s->party_slot_record(s->context, slot, &bytes, &len)) return 0;\n"
                  "    if (!bytes || len < 8u) return 0;\n",
                  "    if (!s->party_slot_record) return 0;\n"
                  "    bytes = p->producer.incoming; len = p->producer.incoming_len;\n")]),
    # §3.2: without the scratch copy the in-place decrypt corrupts s->incoming and the
    # scene is handed something other than the host's record.
    "no-decoder-scratch-copy": (
        (3, 0), [(TP,
                  "    n = len < (unsigned)SLINK_MAX_RECORD ? len : (unsigned)SLINK_MAX_RECORD;\n"
                  "    for (i = 0; i < n; i++) d->owner->decode_scratch[i] = rec[i];\n"
                  "    return s->decode_read_u32(s->context, d->owner->decode_scratch, len, off, out) ? 1 : 0;\n",
                  "    n = len < (unsigned)SLINK_MAX_RECORD ? len : (unsigned)SLINK_MAX_RECORD;\n"
                  "    (void)n; (void)i;\n"
                  "    return s->decode_read_u32(s->context, rec, len, off, out) ? 1 : 0;\n")]),
    # §3.3 step 2 in the scene: an out-of-party slot reaches PARTY_ASSERT_SLOT.
    "no-party-bound-in-scene": (
        (8, 0), [(TP, "    if (!slink_gen4_slot_live(p, slot)) return 0;\n", "")]),
    # §3.3 step 2 at the write site: the last guard before the copy.
    "no-party-bound-at-commit": (
        (9, 0), [(TP, "    if (!slink_gen4_slot_live(p, actual_slot)) return 0;\n", "")]),
    # §3.3 step 1: the located slot alone would let any live slot be overwritten.
    "no-script-chosen-slot-check": (
        (11, 0), [(TP, "    if (slot != chosen) return 0;\n", "")]),
    # §3.3: the copy without its marker is not a guarded abort.
    "commit-without-commit-entered": (
        (10, 0), [(TP, "    if (!(p->witness->milestones & (1u << SLINK_COMMIT_ENTERED))) return 0;\n", "")]),
    # Red controls on the SHARED binding check: without these the refusal scenarios would
    # pass for reasons that have nothing to do with this policy.
    "no-binding-validate": (
        (2, 14), [(COMMON_TP, "    if (!b->validate(e->decoder,s->incoming,len)) return 0;",
                   "    if (0 && !b->validate(e->decoder,s->incoming,len)) return 0;")]),
    "no-claim-cross-check": (
        (2, 8), [(COMMON_TP, "    if (!b->same_identity(&actual,&claimed)) return 0;",
                  "    if (0 && !b->same_identity(&actual,&claimed)) return 0;")]),
}


@pytest.mark.parametrize("mutation", sorted(MUTANTS))
def test_policy_falsifiers_fail_on_known_bad_mutants(tmp_path, mutation):
    scenario, edits = MUTANTS[mutation]
    root = tmp_path / mutation
    shutil.copytree(COMMON, root / "common")
    shutil.copytree(GEN4, root / "gen4")
    for header, needle, replacement in edits:
        path = (root / "common" / header) if header == COMMON_TP else (root / "gen4" / header)
        text = path.read_text(encoding="utf-8")
        assert needle in text, f"{mutation}: needle not found in {header}"
        path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    exe = _build(tmp_path, mutation, HARNESS_C, includes=(root / "common", root / "gen4"))
    done = subprocess.run([str(exe), *map(str, scenario)], capture_output=True, text=True, timeout=30)
    assert done.returncode != 0 and "FAIL line" in done.stdout, (
        f"mutant {mutation} was NOT detected: rc={done.returncode}\n{done.stdout}\n{done.stderr}")


# --------------------------------------------------------------------------- source guards


def _code_without_comments_or_directives(path: Path) -> str:
    text = _strip_comments(path.read_text(encoding="utf-8"))
    kept: list[str] = []
    continuing = False
    for line in text.splitlines():
        if continuing:
            continuing = line.rstrip().endswith("\\")
            continue
        if line.lstrip().startswith("#"):
            continuing = line.rstrip().endswith("\\")
            continue
        kept.append(line)
    return "\n".join(kept)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


@pytest.mark.parametrize("header", [TRADE_H, TP])
def test_no_file_scope_object_in_the_gen4_trade_headers(header):
    """patch/src/nds/gen4/README.md:50-59 and :126-128: a static .bss symbol in this
    directory moves SDK_STATIC_BSS_END and every pinned overlay address above it."""
    body = _code_without_comments_or_directives(GEN4 / header)
    offenders = re.findall(r"^static\s+(?!inline\b).*", body, re.M)
    assert not offenders, f"{header} declares a file-scope object: {offenders}"


@pytest.mark.parametrize("header", [TRADE_H, TP])
def test_gen4_trade_headers_include_only_shared_nds_headers(header):
    """No game header and no Gen 3 ABI: the policy must compile on a host gcc, and
    abi.h:31-33 refuses a translation unit holding both ABIs."""
    text = (GEN4 / header).read_text(encoding="utf-8")
    includes = set(re.findall(r'#include\s+"([^"]+)"', text))
    assert includes <= {"abi.h", "record_binding.h", "trade_producer.h", "trade_policy.h"}, includes
    assert "beacon.h" not in includes, "the policy must not depend on the beacon state struct"


@pytest.mark.parametrize("header", [TRADE_H, TP])
def test_gen4_trade_headers_carry_no_mailbox_span_literal(header):
    """tools/gen4_mailbox_census.py:83 LITERAL rejects a 7-8 hex-digit word inside the
    arena span; the absolute base must be derived, never written."""
    code = _strip_comments((GEN4 / header).read_text(encoding="utf-8"))
    literals = re.findall(r"\b0[xX][0-9A-Fa-f]{7,8}\b", code)
    assert not literals, f"{header} carries span-sized literals: {literals}"


def test_trade_policy_is_party_only_and_has_no_box_arm():
    """Owner ruling DECISIONS_2026-10-02_companion.md:12 / C5_TRADE_SPEC.md:17-19: the box
    arm was dropped. Its symbols must not reappear."""
    code = _strip_comments((GEN4 / TP).read_text(encoding="utf-8"))
    for banned in ("PCStorage", "CountPCEmptySpace", "SLINK_STAGE_OP_BOX"):
        assert banned not in code, f"box-arm symbol {banned} is back in {TP}"
    assert "SLINK_GEN4_PARTY_SLOTS" in code


def test_trade_h_documents_every_open_point_as_a_seam():
    """Card requirement: an OPEN spec point is a seam, never a decision."""
    trade = (GEN4 / TRADE_H).read_text(encoding="utf-8")
    policy = (GEN4 / TP).read_text(encoding="utf-8")
    for seam_member in ("script_chosen_slot", "post_save_poll", "safe_field", "poll_scene",
                        "poll_pre_save", "commit_party_slot", "post_save_begin"):
        assert f"(*{seam_member})(" in policy, f"{seam_member} is not a seam member"
        assert seam_member in trade, f"{seam_member} is not documented in {TRADE_H}"
    # the save-timeout bound stays the caller's argument, never a literal in this policy
    assert "save_timeout_frames" in policy
    assert not re.search(r"SLINK_GEN4_SAVE_TIMEOUT", policy)
