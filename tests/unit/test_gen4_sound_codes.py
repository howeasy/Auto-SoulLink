"""Host-C falsifiers for the Gen 4 companion C3 sound policy (patch/src/nds/gen4).

Mirrors tests/unit/test_nds_common_producers.py: the REAL headers are compiled with
-std=c11 -Wall -Wextra -Werror and driven through a fake engine, so every decision the
policy makes is observed rather than asserted about. Needs a host C compiler
(SLINK_HOST_GCC, PATH, or the repo's w64devkit); skips with a named reason when none
exists, and SLINK_REQUIRE_HOST_CC=1 turns that skip into a failure.

What is provable here and what is not:
  PROVED   code -> SE id; the hole at index 2 and the out-of-range band are refused with
           their named reasons and nothing is played; the epoch gate; the sound-ready
           latch; the 240-visit hold saturates and consumes exactly once; one request in
           flight; foreign opcodes are never acked; the arena accessor refuses a
           non-census base; the capability/reason numbers are in their ruled ranges; and
           the PUBLISHED capability word (beacon.h, Slink_NDS_PublishCaps) is composed
           from the cards after the fan-out -- a card's bit survives the visit, a bit a
           card drops is gone in that same visit, a host write into the word cannot
           survive, bits 7..15 are never published, and a card that is not in the build
           contributes nothing even if its contribution word is set.
  NOT PROVED  that an SE is audible, and which of the four SE handles a given id lands on.
           Both are falsifier F1, a PHYSICAL claim (C3_SOUND_SPEC.md:487, §6 Q3). This
           module never claims them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"
BEACON_C = GEN4 / "beacon.c"
SOUND_H = GEN4 / "sound.h"
CC_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]


def _find_gcc():
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


def _gcc():
    gcc = _find_gcc()
    if not gcc:
        reason = ("no host C compiler (set SLINK_HOST_GCC, put gcc on PATH, or provide "
                  ".cache/build-tools/*/bin/gcc.exe); Gen 4 sound policy falsifiers did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def test_host_c_compiler_is_discoverable():
    """All-skipped must be distinguishable from all-passed: SLINK_REQUIRE_HOST_CC=1 makes absence a failure."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _compile(tmp, name, source, defines=(), gen4=None):
    """Compile `source` against the real headers; `gen4` overrides the per-title directory
    (a mutated copy), so the same driver can be run against a mutant policy."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / f"{name}.c"
    src.write_text(source)
    exe = tmp / f"{name}.exe"
    cmd = [_gcc(), *CC_FLAGS, *defines]
    cmd += ["-I", str(gen4 or GEN4), "-I", str(GEN4), "-I", str(COMMON)]
    cmd += [str(src), "-o", str(exe)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return exe, done


def _build(tmp, name, source, defines=(), gen4=None):
    exe, done = _compile(tmp, name, source, defines, gen4)
    assert done.returncode == 0, done.stderr
    return exe


def _run(exe):
    done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stdout + done.stderr + f" exit={done.returncode}"
    return done.stdout


def _mutant_gen4(tmp, name, filename, anchor, replacement):
    """A copy of the per-title directory with one anchor rewritten. The copy is placed
    FIRST on the include path, so the mutant header really is the one that gets compiled
    (a #include "beacon.h" inside sound.h resolves inside the copy, not the original)."""
    dst = tmp / f"gen4_{name}"
    shutil.copytree(GEN4, dst)
    target = dst / filename
    text = target.read_text(encoding="utf-8")
    assert anchor in text, f"red-control anchor drifted in {filename}: {anchor!r}"
    target.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    return dst


def _census_constants() -> tuple[str, str]:
    """The census value and the arena->span delta are read out of beacon.c and handed to the
    C driver as -D flags, so the arena test measures the REAL constants instead of a copy."""
    text = BEACON_C.read_text(encoding="utf-8")
    start = re.search(r"#define\s+SLINK_GEN4_ARENA_START\s+(0x[0-9A-Fa-f]+)u", text)
    delta = re.search(r"#define\s+SLINK_GEN4_ARENA_DELTA\s+(0x[0-9A-Fa-f]+)u", text)
    assert start and delta, "beacon.c lost the census arena value or the span delta"
    return start.group(1), delta.group(1)


# ------------------------------------------------------------------------------- driver

DRIVER = r'''
#include "sound_policy.h"
#include <stdio.h>
#include <string.h>

/* A fake engine. Nothing here is the game: the five seam members are the only things the
 * policy is allowed to know about sound, which is the point of the seam. */
static int plays, last_se, fading, after_fade, busy;
static void play_se(void *c, uint16_t se) { (void)c; plays++; last_se = (int)se; }
static int fade_fn(void *c) { (void)c; return fading; }
static int after_fn(void *c) { (void)c; return after_fade; }
static int busy_fn(void *c, uint16_t se) { (void)c; (void)se; return busy; }
static SlinkGen4SoundEngine engine = { NULL, fade_fn, after_fn, busy_fn, play_se };

/* The two reasons the spec does NOT name, supplied by the caller. They are deliberately
 * not 32 and not 2, so a test can tell "the policy picked a reason" from "the caller did". */
static SlinkGen4SoundReasons reasons = { 40u, 41u };

static SlinkMailboxV2 mailbox;
static SlinkGen4StateSound sound;
#define EPOCH 0x11223344u

void post(uint16_t seq, uint8_t code, uint32_t epoch)
{
    mailbox.opcode = SLINK_GEN4_SOUND_OPCODE;
    mailbox.seq = seq;
    mailbox.args[0] = code;
    mailbox.session_epoch = epoch;
    mailbox.status = SLINK_ST_BUSY; /* the beacon owns this byte; C3 only holds it */
}
void reset_world(void)
{
    memset(&mailbox, 0, sizeof mailbox);
    memset(&sound, 0, sizeof sound);
    plays = 0; last_se = 0; fading = 0; after_fade = 0; busy = 0;
    slink_gen4_sound_latch_ready(&sound);
}
int step(void) { return slink_gen4_sound_step(&mailbox, &sound, &engine, &reasons, EPOCH); }

/* ---------------------------------------------------------------- the beacon's block
 * The composition the beacon performs after the fan-out (beacon.h,
 * Slink_NDS_PublishCaps), over the state block whose .sound member IS this card's
 * sub-struct. `state.sound = sound` stands for the in-place relationship: in the ROM the
 * card's Service writes state.sound and the beacon composes from it; here the card's
 * sub-struct is a separate object, so one copy brings the two together. */
static SlinkGen4State state;

static void visit(void)
{
    state.sound = sound;
    Slink_NDS_PublishCaps(&state, &mailbox);
}
#define CHECK(c, n) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return (n); } } while (0)

int scen_codes(void)
{
    static const struct { uint8_t code; uint16_t se; } table[] = {
        { 1u, 1501u }, { 3u, 1536u }, { 4u, 1500u }
    };
    uint16_t seq = 7u;
    unsigned i;
    reset_world();
    for (i = 0; i < sizeof table / sizeof table[0]; i++) {
        plays = 0; last_se = 0;
        post(seq, table[i].code, EPOCH);
        CHECK(step() == SLINK_SOUND_PLAYED, 10 + (int)i);
        CHECK(plays == 1 && (uint16_t)last_se == table[i].se, 20 + (int)i);
        CHECK(mailbox.opcode == 0, 30 + (int)i);              /* tp_ack consumed the request */
        CHECK(mailbox.status == SLINK_ST_OK, 40 + (int)i);     /* "handed to PlaySE", not "heard" */
        CHECK(mailbox.ack_seq == seq && mailbox.reason == 0, 50 + (int)i);
        CHECK(sound.in_flight == 0 && sound.hold_visits == 0, 60 + (int)i);
        /* a further visit must not re-fire: the ack consumed the request */
        CHECK(step() == SLINK_SOUND_IDLE, 70 + (int)i);
        CHECK(plays == 1, 80 + (int)i);
        seq++;
    }
    return 0;
}

int scen_refuse(void)
{
    static const uint8_t unknown[] = { 0u, 5u, 255u, 200u };
    unsigned i;
    reset_world();
    /* code 2: the hole. Refused with the title-private reason, named and distinct from the
     * generic bad-args code, and nothing is played (F5). */
    post(1u, 2u, EPOCH);
    CHECK(step() == SLINK_SOUND_REFUSED, 1);
    CHECK(mailbox.reason == SLINK_GEN4_REASON_SOUND_CODE_REFUSED, 2);
    CHECK(mailbox.reason == 32u, 3);
    CHECK(mailbox.reason != SLINK_REASON_BAD_ARGS, 4);
    CHECK(mailbox.status == SLINK_ST_FAIL && mailbox.opcode == 0, 5);
    CHECK(plays == 0 && sound.in_flight == 0, 6);
    /* outside 1..4: consumed unplayed, generic shared reason (F4) */
    for (i = 0; i < sizeof unknown / sizeof unknown[0]; i++) {
        plays = 0;
        post((uint16_t)(2u + i), unknown[i], EPOCH);
        CHECK(step() == SLINK_SOUND_REFUSED, 10 + (int)i);
        CHECK(mailbox.reason == SLINK_REASON_BAD_ARGS, 20 + (int)i);
        CHECK(mailbox.status == SLINK_ST_FAIL && mailbox.opcode == 0, 30 + (int)i);
        CHECK(plays == 0 && sound.in_flight == 0, 40 + (int)i);
    }
    return 0;
}

int scen_hold(void)
{
    unsigned i;
    reset_world();
    fading = 1;
    post(9u, 3u, EPOCH);
    for (i = 1; i < SLINK_GEN4_SOUND_MAX_HOLD_VISITS; i++) {
        CHECK(step() == SLINK_SOUND_HELD, 1);
        CHECK(mailbox.opcode == SLINK_GEN4_SOUND_OPCODE, 2);   /* still held, not queued away */
        CHECK(mailbox.status == SLINK_ST_BUSY, 3);             /* the beacon's byte, untouched */
        CHECK(plays == 0, 4);
        CHECK(sound.hold_visits == i, 5);
    }
    /* the bound visit consumes it, unplayed, with the caller's reason */
    CHECK(step() == SLINK_SOUND_REFUSED, 6);
    CHECK(sound.hold_visits == 0u && sound.in_flight == 0u, 7);   /* released: the next request starts a fresh hold */
    CHECK(plays == 0 && mailbox.opcode == 0, 8);
    CHECK(mailbox.reason == reasons.hold_expired, 9);
    CHECK(sound.in_flight == 0, 10);
    /* consumed once: no re-fire, ever */
    for (i = 0; i < 16u; i++) {
        CHECK(step() == SLINK_SOUND_IDLE, 11);
    }
    CHECK(plays == 0, 12);
    /* a corrupted age saturates instead of wrapping into a fresh hold */
    memset(&sound, 0, sizeof sound);
    slink_gen4_sound_latch_ready(&sound);
    sound.in_flight = 1u;
    sound.hold_visits = 0xFFFFFFFFu;
    plays = 0;
    post(11u, 3u, EPOCH);
    CHECK(step() == SLINK_SOUND_REFUSED, 13);
    CHECK(plays == 0 && mailbox.opcode == 0, 14);
    /* and it saturates upward too: the counter never exceeds the bound */
    reset_world();
    fading = 1;
    sound.hold_visits = SLINK_GEN4_SOUND_MAX_HOLD_VISITS - 1u;
    sound.in_flight = 1u;
    post(12u, 1u, EPOCH);
    CHECK(step() == SLINK_SOUND_REFUSED, 15);
    CHECK(sound.hold_visits == 0, 16);
    return 0;
}

int scen_inflight(void)
{
    reset_world();
    fading = 1;
    /* one slot: NDS has a single u16 opcode, so a second post overwrites rather than queues */
    post(21u, 1u, EPOCH);
    CHECK(step() == SLINK_SOUND_HELD, 1);
    mailbox.seq = 22u;
    mailbox.args[0] = 4u;
    CHECK(step() == SLINK_SOUND_HELD, 2);
    CHECK(plays == 0, 3);
    /* released: exactly one sound, for the request that is published now */
    fading = 0;
    CHECK(step() == SLINK_SOUND_PLAYED, 4);
    CHECK(plays == 1 && last_se == 1500, 5);
    CHECK(mailbox.opcode == 0 && sound.in_flight == 0, 6);
    CHECK(step() == SLINK_SOUND_IDLE, 7);
    CHECK(plays == 1, 8);
    /* the handle-busy guard. The seam is per SEQ because the ROM resolves the handle from
     * the seq at runtime (the sound ARCHIVE owns the mapping); the fake answers for
     * whichever seq it is handed, so this is the "same seq still occupying its handle" case */
    reset_world();
    busy = 1;
    post(31u, 3u, EPOCH);
    CHECK(step() == SLINK_SOUND_HELD, 9);
    CHECK(plays == 0, 10);
    busy = 0;
    CHECK(step() == SLINK_SOUND_PLAYED, 11);
    CHECK(plays == 1 && last_se == 1536, 12);
    /* the after-fade guard is the third hold predicate */
    reset_world();
    after_fade = 1;
    post(41u, 4u, EPOCH);
    CHECK(step() == SLINK_SOUND_HELD, 13);
    after_fade = 0;
    CHECK(step() == SLINK_SOUND_PLAYED, 14);
    CHECK(plays == 1 && last_se == 1500, 15);
    return 0;
}

int scen_notready(void)
{
    memset(&mailbox, 0, sizeof mailbox);
    memset(&sound, 0, sizeof sound);
    /* before InitSoundData there is no sound system: an empty visit still latches blocked
     * and acks nothing (the reset latch wins over "no request", sfx.asm:34-36) */
    CHECK(step() == SLINK_SOUND_IDLE, 1);
    CHECK(sound.blocked == 1, 2);
    CHECK(mailbox.opcode == 0 && mailbox.ack_seq == 0 && mailbox.status == 0, 3);
    /* a request in that window is REFUSED, not queued for later */
    post(5u, 4u, EPOCH);
    CHECK(step() == SLINK_SOUND_REFUSED, 4);
    CHECK(mailbox.reason == reasons.not_ready, 5);
    CHECK(mailbox.status == SLINK_ST_FAIL && mailbox.opcode == 0, 6);
    CHECK(plays == 0 && sound.in_flight == 0, 7);
    /* the latch fires; the next visit releases the block and plays a fresh request */
    slink_gen4_sound_latch_ready(&sound);
    post(6u, 4u, EPOCH);
    CHECK(step() == SLINK_SOUND_PLAYED, 8);
    CHECK(plays == 1 && last_se == 1500, 9);
    CHECK(sound.blocked == 0, 10);
    return 0;
}

int scen_epoch(void)
{
    reset_world();
    post(1u, 1u, 0u);
    CHECK(step() == SLINK_SOUND_REFUSED, 1);
    CHECK(mailbox.reason == SLINK_REASON_CLIENT_TOO_OLD, 2);
    CHECK(plays == 0, 3);
    post(2u, 1u, EPOCH + 1u);
    CHECK(step() == SLINK_SOUND_REFUSED, 4);
    CHECK(mailbox.reason == SLINK_REASON_IDENTITY, 5);
    CHECK(plays == 0 && mailbox.opcode == 0, 6);
    post(3u, 1u, EPOCH);
    CHECK(step() == SLINK_SOUND_PLAYED, 7);
    CHECK(plays == 1, 8);
    /* a stale request from the previous boot is refused, not played: the mailbox is in ITCM
     * and survives a soft reset (C3_SOUND_SPEC.md:268-275) */
    return 0;
}

int scen_foreign(void)
{
    reset_world();
    /* opcode 9 (PLAY_FANFARE) is unwired on Gen 4 (C3_SOUND_SPEC.md:90): no ack, no play */
    mailbox.opcode = SLINK_OP_PLAY_FANFARE;
    mailbox.seq = 3u;
    mailbox.session_epoch = EPOCH;
    CHECK(step() == SLINK_SOUND_FOREIGN, 1);
    CHECK(mailbox.status == 0 && mailbox.ack_seq == 0 && mailbox.opcode == SLINK_OP_PLAY_FANFARE, 2);
    CHECK(plays == 0, 3);
    /* C5's opcodes are equally foreign while nothing sound is outstanding */
    mailbox.opcode = SLINK_OP_TRADE_PREPARE;
    mailbox.seq = 4u;
    CHECK(step() == SLINK_SOUND_FOREIGN, 4);
    CHECK(mailbox.ack_seq == 0 && mailbox.reason == 0, 5);
    /* a hold whose slot was taken over is abandoned WITHOUT an ack: the request is not ours */
    fading = 1;
    post(5u, 3u, EPOCH);
    CHECK(step() == SLINK_SOUND_HELD, 6);
    CHECK(sound.in_flight == 1, 7);
    mailbox.opcode = SLINK_OP_TRADE_STATUS;
    mailbox.seq = 6u;
    CHECK(step() == SLINK_SOUND_FOREIGN, 8);
    CHECK(sound.in_flight == 0, 9);
    CHECK(mailbox.ack_seq == 0 && plays == 0, 10);
    return 0;
}

int scen_arena(void)
{
    /* the census value and the delta come from beacon.c via -D, so this is the real rule */
    uint32_t base = Slink_NDS_SpanBase(SLINK_TEST_CENSUS, SLINK_TEST_CENSUS, SLINK_TEST_DELTA);
    CHECK(base == (uint32_t)(SLINK_TEST_CENSUS + SLINK_TEST_DELTA), 1);
    /* fail closed: any other linker value means the span is not where the host reads it */
    CHECK(Slink_NDS_SpanBase(SLINK_TEST_CENSUS + 4u, SLINK_TEST_CENSUS, SLINK_TEST_DELTA) == 0u, 2);
    CHECK(Slink_NDS_SpanBase(0u, SLINK_TEST_CENSUS, SLINK_TEST_DELTA) == 0u, 3);
    CHECK(Slink_NDS_SpanBase(SLINK_TEST_CENSUS, 0u, SLINK_TEST_DELTA) == 0u, 4);
    CHECK(Slink_NDS_SpanBase(0xFFFFFFFFu, SLINK_TEST_CENSUS, SLINK_TEST_DELTA) == 0u, 5);
    return 0;
}

int scen_numbers(void)
{
    /* D-C3-1: NOTIFY is the title-private bit 16, inside 16..31 and outside the shared 0..6 */
    CHECK(SLINK_GEN4_CAP_SE_NOTIFY == (1u << 16), 1);
    CHECK((SLINK_GEN4_CAP_SE_NOTIFY & SLINK_GEN4_CAP_MASK_TITLE) != 0u, 2);
    CHECK((SLINK_GEN4_CAP_SE_NOTIFY & 0x7Fu) == 0u, 3);
    CHECK((SLINK_GEN4_SOUND_CAPABILITIES & SLINK_CAP_NATIVE_SOUND) != 0u, 4);
    CHECK((SLINK_GEN4_SOUND_CAPABILITIES & SLINK_GEN4_CAP_MASK_TITLE)
          == SLINK_GEN4_CAP_SE_NOTIFY, 5);
    /* D-C3-2: reason 32 is title-private (32..63) and distinct from every shared reason */
    CHECK(SLINK_GEN4_REASON_SOUND_CODE_REFUSED == 32u, 6);
    CHECK(SLINK_GEN4_REASON_SOUND_CODE_REFUSED != SLINK_REASON_BAD_ARGS, 7);
    CHECK(SLINK_GEN4_REASON_SOUND_CODE_REFUSED != SLINK_REASON_IDENTITY, 8);
    CHECK(SLINK_GEN4_REASON_SOUND_CODE_REFUSED != SLINK_REASON_CLIENT_TOO_OLD, 9);
    CHECK(SLINK_GEN4_REASON_SOUND_CODE_REFUSED < 64u, 10);
    /* the code table is the spec's, and the hold bound is Gen 2's */
    CHECK(SLINK_GEN4_SE_SUCCESS == 1501u && SLINK_GEN4_SE_BOO == 1536u
          && SLINK_GEN4_SE_NOTIFY == 1500u, 11);
    CHECK(SLINK_GEN4_SOUND_MAX_HOLD_VISITS == 240u, 12);
    CHECK(SLINK_GEN4_SOUND_CODE_MAX == 4u && SLINK_GEN4_SOUND_OPCODE == SLINK_OP_PLAY_SE, 13);
    /* the state block: fixed size per card, versioned, zero at allocation (layout 0) */
    CHECK(sizeof(SlinkGen4StateSound) == 16u, 14);
    CHECK(SLINK_GEN4_STATE_SOUND_LAYOUT == 1u && SLINK_GEN4_STATE_PANEL_LAYOUT == 1u
          && SLINK_GEN4_STATE_TRADE_LAYOUT == 1u, 15);
    return 0;
}

int scen_caps(void)
{
    memset(&state, 0, sizeof state);
    memset(&mailbox, 0, sizeof mailbox);
    memset(&sound, 0, sizeof sound);

    /* 1. C3 has run and is NOT ready (no InitSoundData yet), so it contributes nothing and
     *    the published word is the beacon's own set, which is zero at C2. */
    CHECK(step() == SLINK_SOUND_IDLE, 1);
    visit();
    CHECK(state.sound.caps == 0u, 2);
    CHECK(mailbox.capabilities == SLINK_GEN4_CAPABILITIES, 3);

    /* 2. the latch: C3's contribution appears and the host sees it in the same visit. The
     *    bit is C3's own (D-C3-1) and no other card is in the word yet. */
    slink_gen4_sound_latch_ready(&sound);
    CHECK(step() == SLINK_SOUND_IDLE, 4);
    visit();
    CHECK(state.sound.caps == SLINK_GEN4_SOUND_CAPABILITIES, 5);
    CHECK(mailbox.capabilities == (SLINK_CAP_NATIVE_SOUND | SLINK_GEN4_CAP_SE_NOTIFY), 6);
    CHECK((mailbox.capabilities & SLINK_CAP_DURABLE_TRADE) == 0u, 7);

    /* 3. C5 declares its contribution (trade.h step 5) and the composed word keeps it --
     *    the defect this composition exists to fix: the beacon stamped over it before. */
    state.trade.caps = SLINK_CAP_DURABLE_TRADE;
    visit();
    CHECK(mailbox.capabilities
          == (SLINK_CAP_NATIVE_SOUND | SLINK_GEN4_CAP_SE_NOTIFY | SLINK_CAP_DURABLE_TRADE), 8);

    /* 4. C4 likewise -- and a card that stops declaring loses its bit in the SAME visit */
    state.panel.caps = SLINK_CAP_INFO_PANEL;
    visit();
    CHECK((mailbox.capabilities & SLINK_CAP_INFO_PANEL) != 0u, 9);
    state.panel.caps = 0u;
    visit();
    CHECK((mailbox.capabilities & SLINK_CAP_INFO_PANEL) == 0u, 10);

    /* 5. a host write into the mailbox cannot survive: the word is rebuilt from state, so
     *    nothing it wrote (nor the previous visit's word) is ever carried forward. */
    mailbox.capabilities = 0xFFFFFFFFu;
    visit();
    CHECK(mailbox.capabilities
          == (SLINK_CAP_NATIVE_SOUND | SLINK_GEN4_CAP_SE_NOTIFY | SLINK_CAP_DURABLE_TRADE), 11);

    /* 6. bits 7..15 are reserved for future shared caps and are dropped on the way out,
     *    from any card: the card's own word is left alone, the published word is not. */
    sound.caps = SLINK_GEN4_SOUND_CAPABILITIES | 0x0000FF80u;
    state.trade.caps = 0x00008100u;
    visit();
    CHECK((sound.caps & 0x0000FF80u) != 0u, 12);
    CHECK((mailbox.capabilities & 0x0000FF80u) == 0u, 13);
    CHECK(mailbox.capabilities == (SLINK_CAP_NATIVE_SOUND | SLINK_GEN4_CAP_SE_NOTIFY), 14);

    /* 7. a title-private bit stays title-private: it never lands in the shared 0..15 */
    sound.caps = SLINK_CAP_NATIVE_SOUND;
    state.trade.caps = 0x00010000u;
    visit();
    CHECK((mailbox.capabilities & SLINK_GEN4_CAP_MASK_TITLE) == 0x00010000u, 15);
    CHECK((mailbox.capabilities & 0xFFFFu) == SLINK_CAP_NATIVE_SOUND, 16);

    /* 8. fail closed: no block, no stamp (beacon.c has already returned on either) */
    mailbox.capabilities = SLINK_CAP_NATIVE_SOUND;
    Slink_NDS_PublishCaps(NULL, &mailbox);
    CHECK(mailbox.capabilities == SLINK_CAP_NATIVE_SOUND, 17);
    Slink_NDS_PublishCaps(&state, NULL);
    CHECK(mailbox.capabilities == SLINK_CAP_NATIVE_SOUND, 18);
    return 0;
}

int scen_nocards(void)
{
    /* This binary is built WITHOUT SLINK_GEN4_SOUND/PANEL/TRADE. A contribution word no
     * card in this build can own -- stale bytes, a speculative module -- must never reach
     * the published word: "no card may set a bit ahead of its own" is enforced by the
     * composition, not by reviewer discipline (C2_BEACON_SPEC.md:432-435). */
    memset(&state, 0, sizeof state);
    memset(&mailbox, 0, sizeof mailbox);
    state.sound.caps = SLINK_GEN4_SOUND_CAPABILITIES;
    state.panel.caps = SLINK_CAP_INFO_PANEL;
    state.trade.caps = SLINK_CAP_DURABLE_TRADE;
    Slink_NDS_PublishCaps(&state, &mailbox);
    CHECK(mailbox.capabilities == SLINK_GEN4_CAPABILITIES, 1);
    return 0;
}

int main(void)
{
#if SCENARIO == 1
    return scen_codes();
#elif SCENARIO == 2
    return scen_refuse();
#elif SCENARIO == 3
    return scen_hold();
#elif SCENARIO == 4
    return scen_inflight();
#elif SCENARIO == 5
    return scen_notready();
#elif SCENARIO == 6
    return scen_epoch();
#elif SCENARIO == 7
    return scen_foreign();
#elif SCENARIO == 8
    return scen_arena();
#elif SCENARIO == 9
    return scen_numbers();
#elif SCENARIO == 10
    return scen_caps();
#elif SCENARIO == 11
    return scen_nocards();
#else
#error "no scenario selected"
#endif
}
'''

SCENARIOS = {
    1: "code table reaches the right SE",
    2: "code 2 and out-of-range codes are refused, named, silent",
    3: "the 240-visit hold saturates and consumes exactly once",
    4: "one sound in flight, and every hold predicate holds",
    5: "the InitSoundData latch refuses before it releases",
    6: "the epoch gate refuses zero and mismatched epochs",
    7: "foreign opcodes are never acked",
    8: "the arena accessor refuses a non-census base",
    9: "capability, reason, table and layout numbers",
    10: "the composed capability word: survives, drops, survives a host write",
    11: "no card arm without its card in this build",
}


def _defines(scenario):
    """The build the scenario needs. Scenario 10 is compiled WITH all three cards, so
    every arm of the composition is real; scenario 11 is compiled WITHOUT them, which is
    the whole point of it. The red controls take the same defines as the green test, or
    a control could trip for a missing -D instead of for its mutation."""
    census, delta = _census_constants()
    defines = [f"-DSCENARIO={scenario}",
               f"-DSLINK_TEST_CENSUS={census}u",
               f"-DSLINK_TEST_DELTA={delta}u"]
    if scenario == 10:
        defines += ["-DSLINK_GEN4_SOUND", "-DSLINK_GEN4_PANEL", "-DSLINK_GEN4_TRADE"]
    return defines


def _drive(tmp_path, scenario):
    return _build(tmp_path / f"s{scenario}", "sound", DRIVER, defines=_defines(scenario))


@pytest.mark.parametrize("scenario", sorted(SCENARIOS), ids=[f"{n}-{SCENARIOS[n]}" for n in sorted(SCENARIOS)])
def test_sound_policy_scenarios(tmp_path, scenario):
    _run(_drive(tmp_path, scenario))


# ------------------------------------------------------------------------------- source

def test_the_hole_has_no_placeholder_id():
    """F5: "the code table has a hole at index 2 rather than a placeholder id". A macro
    named for the FAILURE sound would be exactly the guess the owner ruling forbids."""
    text = SOUND_H.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#include"))
    assert not re.search(r"#define\s+SLINK_GEN4_SE_FAILURE\b", code)
    assert not re.search(r"#define\s+SLINK_GEN4_SE_PLACEHOLDER\b", code)
    # and no SE id is wired to the recorded substitution either (SEQ_SE_DP_DECIDE2 = 1694)
    assert "1694" not in code


def test_the_arena_base_is_exported_once_and_used():
    """The interface hole this card closed: one fail-closed accessor, no per-card re-derivation."""
    header = (GEN4 / "beacon.h").read_text(encoding="utf-8")
    body = BEACON_C.read_text(encoding="utf-8")
    assert "uint32_t Slink_NDS_ArenaBase(void);" in header
    assert re.search(r"uint32_t\s+Slink_NDS_ArenaBase\(void\)\s*\n\{", body)
    # beacon.c binds the exported accessor to the exported rule, it does not re-implement it
    assert "Slink_NDS_SpanBase(" in body
    assert "Slink_NDS_ArenaBase() == 0u" in body
    for name in ("sound.h", "sound_policy.h", "dispatch.c"):
        text = (GEN4 / name).read_text(encoding="utf-8")
        assert "SDK_SECTION_ARENA_ITCM_START" not in text, name
        assert "SLINK_GEN4_ARENA_START" not in text, name


def test_the_policy_needs_no_game_header_and_no_file_scope_object():
    """sound_policy.h is host-compilable and object-free: no static, no const table.
    Comments are stripped first, because the header explains both rules in prose."""
    raw = (GEN4 / "sound_policy.h").read_text(encoding="utf-8")
    assert '#include "sound.h"' in raw and '#include "trade_producer.h"' in raw
    policy = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
    for banned in ("static const", "static uint", "static int", "static Slink"):
        assert banned not in policy, banned
    # every file-scope definition in the policy is a function; the code table is a switch,
    # so there is no array that could hold a placeholder id
    assert "switch (code)" in policy
    assert not [ln for ln in policy.splitlines() if ln.startswith("static ") and "(" not in ln]


# ---------------------------------------------------------------------------- red controls
# Each mutates a COPY of the real per-title headers and re-runs the SAME scenario the green
# test above runs. A control that stays green means its detector measures nothing.

_CONTROLS = [
    # (id, file, anchor, replacement, scenario)
    ("maps the hole to a sound",
     "sound_policy.h", "case SLINK_GEN4_SOUND_CODE_FAILURE: return 0;",
     "case SLINK_GEN4_SOUND_CODE_FAILURE: *out_se = (uint16_t)SLINK_GEN4_SE_SUCCESS; return 1;", 2),
    ("skips the hold",
     "sound_policy.h", "if (slink_gen4_sound_blocked(e, se)) {",
     "if (0) {", 3),
    ("plays while the sound system is uninitialised",
     "sound_policy.h", "if (s->ready == 0u) {", "if (0) {", 5),
    ("acks a foreign opcode",
     "sound_policy.h", "return (m->opcode == 0) ? SLINK_SOUND_IDLE : SLINK_SOUND_FOREIGN;",
     "return SLINK_SOUND_IDLE;", 7),
    ("the arena accessor stops failing closed",
     "beacon.h", "if (arena_lo != census_arena_lo) {", "if (arena_lo != census_arena_lo && 0) {", 8),
    # D-C3-1 / C2: the published word is composed from the cards, assigned (never
    # accumulated), masked, and only from cards that are in THIS build.
    ("accumulates the previous word",
     "beacon.h", "    m->capabilities = caps & SLINK_GEN4_CAP_MASK_LEGAL;",
     "    m->capabilities |= caps & SLINK_GEN4_CAP_MASK_LEGAL;", 10),
    ("stamps the beacon's constant instead of the cards'",
     "beacon.h", "    m->capabilities = caps & SLINK_GEN4_CAP_MASK_LEGAL;",
     "    m->capabilities = SLINK_GEN4_CAPABILITIES; (void)caps;", 10),
    ("publishes the reserved bits 7..15",
     "beacon.h", "caps & SLINK_GEN4_CAP_MASK_LEGAL;", "caps;", 10),
    ("lets a card advertise ahead of itself",
     "beacon.h", "#if defined(SLINK_GEN4_SOUND)\n    caps |= st->sound.caps;\n#endif",
     "    caps |= st->sound.caps;", 11),
]


@pytest.mark.parametrize("label,filename,anchor,replacement,scenario",
                         _CONTROLS, ids=[c[0] for c in _CONTROLS])
def test_red_controls(tmp_path, label, filename, anchor, replacement, scenario):
    census, delta = _census_constants()
    gen4 = _mutant_gen4(tmp_path, label.replace(" ", "_"), filename, anchor, replacement)
    exe, done = _compile(tmp_path / f"m{scenario}", "mutant", DRIVER,
                         defines=_defines(scenario), gen4=gen4)
    assert done.returncode == 0, f"control {label!r} does not even compile: {done.stderr}"
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert run.returncode != 0, f"red control {label!r} did not trip"
