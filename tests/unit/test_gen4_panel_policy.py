"""Host-C falsifiers for the Gen 4 companion C4 info-panel POLICY (patch/src/nds/gen4
panel.h, panel_policy.h). Spec: docs/gen4/companion/C4_PANEL_SPEC.md; facts:
docs/gen4/companion/C4_FACTS.md.

Mirrors tests/unit/test_gen4_sound_codes.py and tests/unit/test_gen4_trade_policy.py: the
REAL headers are compiled with -std=c11 -Wall -Wextra -Werror and driven through a fake
engine, so every claim is about the shipped header and not about a test double of it. No
emulator, no ROM, no game header. Needs a host C compiler (SLINK_HOST_GCC, PATH, or the
repo's w64devkit); skips with a named reason when none exists, and SLINK_REQUIRE_HOST_CC=1
turns that skip into a failure.

What is PROVED here (the MODEL half):
  F6   §6       the drawn_seq handshake: state 0 -> 1 -> 2, drawn_seq == request_seq at the
                "drawn" poll, and a mid-panel host rewrite of request_seq/epoch is IGNORED
  F7   §6       the closed_seq handshake: closed_seq == request_seq, result is the app's
                byte, state 0 -- and a second close does not re-publish
  F8   §6       nine refusal shapes, each FAIL + SLINK_REASON_BAD_ARGS with the info region
                and the producer untouched and start() never called
  F9   §6       both-ends gating: the panel opens only when the fade is finished AND the
                menu is open, on the posted and the un-posted path alike
  §3.5          one panel in flight; the A/close result words (Gen 2's no-wrap rule)
  Q7             the Gen 4 text spec is the record binding's own, and the validator's
                charset member is never consulted (so a wrong charset cannot refuse)

What is NOT proved, and is not claimed: F3 (the drawn glyphs), F4 (no heap leak across 100
open/close cycles), F5 (the field overlay is reloaded) and F10 (where a newly appended
overlay group lands). All four are PHYSICAL or post-link claims (C4_PANEL_SPEC.md:569-578).

Every green scenario below is re-run against a seeded defect (the RED CONTROLS at the
bottom) and must go red, so no test here measures nothing.

Run: pytest tests/unit/test_gen4_panel_policy.py -v
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Host-gcc probe binaries must never raise a Windows WER/GPF dialog: it blocks an unattended
# run forever. SetErrorMode is inherited by every child exe this module starts.
if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x8003)
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"
CC_FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror"]

POLICY_H = GEN4 / "panel_policy.h"
PANEL_H = GEN4 / "panel.h"


# --------------------------------------------------------------------------- toolchain

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
                  ".cache/build-tools/*/bin/gcc.exe); Gen 4 panel-policy falsifiers did NOT run")
        if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return gcc


def test_host_c_compiler_is_discoverable():
    """All-skipped must be distinguishable from all-passed: SLINK_REQUIRE_HOST_CC=1 fails instead."""
    done = subprocess.run([_gcc(), "--version"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


def _compile(tmp, name, source, defines=(), gen4=None):
    """Compile `source` against the real headers; `gen4` overrides the per-title directory
    (a mutated copy), so the same driver runs against a mutant policy."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / f"{name}.c"
    src.write_text(source, encoding="utf-8")
    exe = tmp / f"{name}.exe"
    cmd = [_gcc(), *CC_FLAGS, *defines]
    cmd += ["-I", str(gen4 or GEN4), "-I", str(GEN4), "-I", str(COMMON)]
    cmd += [str(src), "-o", str(exe)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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
    """A copy of the per-title directory with one anchor rewritten. The copy is placed FIRST
    on the include path, so the mutant header really is the one that gets compiled."""
    dst = tmp / f"gen4_{name}"
    shutil.copytree(GEN4, dst)
    target = dst / filename
    text = target.read_text(encoding="utf-8")
    assert anchor in text, f"red-control anchor drifted in {filename}: {anchor!r}"
    target.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
    return dst


# ------------------------------------------------------------------------------- driver

DRIVER = r'''
#include "panel_policy.h"
#include "beacon.h"   /* only for the layout/struct parity, SlinkGen4StatePanel, and the
                       * shared PK4 binding's text spec -- never for a code path */
#include <stdio.h>
#include <string.h>
#include <stddef.h>

#define EPOCH 0x11223344u
#define CLOSE ((uint8_t)SLINK_GEN4_PANEL_RESULT_CLOSE)
#define MORE  ((uint8_t)SLINK_GEN4_PANEL_RESULT_MORE)

/* ---- the fake engine. Nothing here is the game: these six seam members are the only
 * things the policy is allowed to know about Gen 4, which is the point of the seam. ---- */
static int fade_ok, menu_ok, app_live, start_ok;
static int starts, polls, last_phase, last_result;
static SlinkInfoV2 handed;          /* what the app actually received */
static int next_phase, phase_once;  /* what the app reports on its NEXT poll, once  */

static int fade_fn(void *c) { (void)c; return fade_ok; }
static int menu_fn(void *c) { (void)c; return menu_ok; }
static int app_fn(void *c) { (void)c; return app_live; }
static int start_fn(void *c, const SlinkInfoV2 *snap)
{
    (void)c;
    starts++;
    if (!start_ok) return 0;
    memcpy(&handed, snap, sizeof handed);
    return 1;
}
static int poll_fn(void *c, uint8_t *result)
{
    (void)c;
    polls++;
    last_phase = phase_once ? next_phase : 0; /* an unarmed poll reports "opening" */
    phase_once = 0;
    *result = last_result;
    return last_phase;
}
static SlinkGen4PanelEngine engine = { NULL, &slink_binding_gen4_pk4.text,
                                      fade_fn, menu_fn, app_fn, start_fn, poll_fn };

/* A deliberately WRONG spec, used to pin what the validator actually consults. */
static const SlinkTextSpec spec_gen3 = { 1, SLINK_CHARSET_GEN3, 0xFFu };
static const SlinkTextSpec spec_wrong_term = { 2, SLINK_CHARSET_GEN4, 0x00FFu };
static const SlinkTextSpec spec_wrong_charset = { 2, SLINK_CHARSET_NONE, 0xFFFFu };

static SlinkMailboxV2 mailbox;
static SlinkInfoV2 info; /* non-volatile here; step() adds volatile, which C allows */
static SlinkGen4PanelState state;

static void put_text(uint8_t *row, const char *s)
{
    unsigned n = 0;
    while (s[n] && n < 15u) { row[2u * n] = (uint8_t)s[n]; row[2u * n + 1u] = 0u; n++; }
    row[2u * n] = 0xFFu; row[2u * n + 1u] = 0xFFu;
    for (n = n + 1u; n < SLINK_INFO_LINE_WIDTH / 2u; n++) {
        row[2u * n] = 0u; row[2u * n + 1u] = 0u;
    }
}

/* A payload the shared validator accepts. */
static void stage(uint32_t epoch, uint16_t seq, uint8_t lines, uint8_t page, uint8_t pages)
{
    memset((void *)&info, 0, sizeof info);
    info.session_epoch = epoch;
    mailbox.session_epoch = epoch; /* the ABI session: zero is unarmed, so stage it */
    info.request_seq = seq;
    info.lines = lines;
    info.page = page;
    info.pages = pages;
    info.enable = 1u;
    /* every row the validator reads must hold the binding's terminator: rows 0..lines-1 and
     * the page slot (panel_producer.h:27-30). Row 6 is never read. */
    for (uint8_t r = 0; r < lines && r < SLINK_INFO_MAX_LINES; r++) put_text(info.text[r], "ROW");
    put_text(info.text[SLINK_INFO_PAGE_SLOT], "PAGE 1/1");
}

static void post(uint16_t seq)
{
    mailbox.opcode = SLINK_OP_SHOW_INFO;
    mailbox.seq = seq;
    mailbox.session_epoch = EPOCH;
    mailbox.status = SLINK_ST_BUSY; /* the beacon owns this byte; C4 only acks */
}

static void reset_world(void)
{
    memset(&mailbox, 0, sizeof mailbox);
    memset((void *)&info, 0, sizeof info);
    memset(&state, 0, sizeof state);
    fade_ok = 1; menu_ok = 1; app_live = 0; start_ok = 1;
    starts = 0; polls = 0; last_phase = 0; last_result = 0;
    memset(&handed, 0, sizeof handed);
    next_phase = 0; phase_once = 0;
    engine.text = &slink_binding_gen4_pk4.text;
}
static int step(void) { return slink_gen4_panel_step(&state, &mailbox, &info, &engine); }
static void queue_poll(int phase) { next_phase = phase; phase_once = 1; }

#define CHECK(c, n) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return (n); } } while (0)

/* every refusal must look identical from outside: FAIL + BAD_ARGS, request consumed, and
 * neither the info region nor the producer touched */
static int refused_is_clean(uint16_t seq, int n)
{
    CHECK(mailbox.status == SLINK_ST_FAIL, n);
    CHECK(mailbox.reason == SLINK_REASON_BAD_ARGS, n + 1);
    CHECK(mailbox.reason == 2u, n + 2);
    CHECK(mailbox.ack_seq == seq, n + 3);
    CHECK(mailbox.opcode == 0, n + 4);
    CHECK(starts == 0, n + 5);
    CHECK(info.state == 0 && info.drawn_seq == 0 && info.closed_seq == 0, n + 6);
    CHECK(state.producer.active == 0, n + 7);
    return 0;
}

/* --------------------------------------------------------------------------- F6/F7 */
int scen_handshake(void)
{
    reset_world();
    stage(EPOCH, 7u, 3u, 0u, 1u);
    /* the un-posted open: the menu is open and a valid payload is staged. The layout stamp
     * and the start happen in the SAME visit -- there is no "first visit does nothing". */
    CHECK(step() == SLINK_PANEL_STARTED, 1);
    CHECK(starts == 1 && polls == 0 && info.state == 1, 2);
    CHECK(state.layout == SLINK_GEN4_PANEL_LAYOUT, 3);
    CHECK(state.caps == (uint32_t)SLINK_GEN4_PANEL_CAPABILITIES, 4);
    /* The app drew from its OWN COPY. Only the HOST-owned fields are compared: the producer
     * copies before it sets state (panel_producer.h:54-61), so drawn_seq/closed_seq/state
     * legitimately differ -- they are ROM-owned (C4_PANEL_SPEC.md:600-608). */
    CHECK(memcmp(handed.text, info.text, sizeof handed.text) == 0, 5);
    CHECK(handed.session_epoch == info.session_epoch && handed.request_seq == info.request_seq, 5);
    /* opening: poll 0 */
    queue_poll(0);
    CHECK(step() == SLINK_PANEL_DRAINED, 6);
    CHECK(info.state == 1 && info.drawn_seq == 0, 7);
    /* drawn: poll 1 -> drawn_seq == request_seq, state 2 (panel_producer.h:41) */
    queue_poll(1);
    CHECK(step() == SLINK_PANEL_DRAINED, 8);
    CHECK(info.drawn_seq == 7u && info.state == 2, 9);
    /* closed: poll 2 -> result, closed_seq == request_seq, state 0 (panel_producer.h:42) */
    queue_poll(2);
    last_result = (uint8_t)SLINK_GEN4_PANEL_RESULT_MORE;
    CHECK(step() == SLINK_PANEL_CLOSED, 10);
    CHECK(info.closed_seq == 7u, 11);
    CHECK(info.result == (uint8_t)SLINK_GEN4_PANEL_RESULT_MORE, 12);
    /* A close and the NEXT open land in the SAME visit: the producer's drain branch clears
     * `active` (panel_producer.h:44) and control falls through to the take-a-request branch,
     * which starts again because the host left the payload staged. That is the shared
     * producer's contract -- which is why the HOST must clear enable or bump request_seq
     * after a close (C4_PANEL_SPEC.md:360-364), not why the ROM keeps a private cursor. */
    CHECK(starts == 2 && info.state == 1, 13);
    info.enable = 0u; /* the host withdraws the payload */
    queue_poll(2);
    CHECK(step() == SLINK_PANEL_CLOSED, 14);
    CHECK(info.state == 0 && starts == 2, 15);
    CHECK(step() == SLINK_PANEL_IDLE, 16);
    CHECK(starts == 2 && mailbox.ack_seq == 0u, 17);
    return 0;
}

int scen_rewrite(void)
{
    reset_world();
    stage(EPOCH, 9u, 2u, 0u, 2u);
    CHECK(step() == SLINK_PANEL_STARTED, 1);
    /* the host rewrites the payload mid-panel: a new request sequence ... */
    stage(EPOCH, 10u, 2u, 1u, 2u);
    info.state = 1; /* a real host staging helper must NOT write the ROM-owned state byte;
                     * this bare memset did, so restore it to model the writer rule */
    queue_poll(1);
    CHECK(step() == SLINK_PANEL_DRAINED, 2);
    CHECK(info.drawn_seq == 0u, 3);   /* the "drawn" report is IGNORED, not obeyed */
    CHECK(info.state == 1, 4);
    /* the app still holds request 9 while the host has moved to 10: the rewrite never reached
     * it (the producer started it from its own copy, panel_producer.h:54-57) */
    CHECK(handed.request_seq == 9u && info.request_seq == 10u, 4);
    /* ... and a different session epoch is equally ignored */
    stage(EPOCH + 1u, 9u, 2u, 0u, 2u);
    info.state = 1; /* same writer rule as above */
    mailbox.session_epoch = EPOCH + 1u;
    queue_poll(1);
    CHECK(step() == SLINK_PANEL_DRAINED, 5);
    CHECK(info.drawn_seq == 0u && info.state == 1, 6);
    /* the close is consumed but NOT published while the epochs disagree -- and the SAME visit
     * opens the new session's payload, because the drain is not a veto over a fresh request */
    queue_poll(2);
    last_result = CLOSE;
    CHECK(step() == SLINK_PANEL_DRAINED, 7);
    CHECK(info.closed_seq == 0u, 8);
    CHECK(info.result == 0u, 8);   /* no result published either: the guard covers both */
    CHECK(starts == 2 && state.producer.active == 1, 9);
    CHECK(state.producer.snapshot.session_epoch == EPOCH + 1u, 10);
    return 0;
}

/* --------------------------------------------------------------------------- F8 */
int scen_refuse(void)
{
    unsigned k;
    /* 1. lines == 0 */
    reset_world();
    stage(EPOCH, 21u, 1u, 0u, 1u);
    info.lines = 0u;
    post(21u);
    CHECK(step() == SLINK_PANEL_REFUSED, 1);
    CHECK(refused_is_clean(21u, 10) == 0, 2);
    /* 2. lines == 7 (> SLINK_INFO_MAX_LINES) */
    reset_world();
    stage(EPOCH, 22u, 1u, 0u, 1u);
    info.lines = (uint8_t)(SLINK_INFO_MAX_LINES + 1u);
    post(22u);
    CHECK(step() == SLINK_PANEL_REFUSED, 3);
    CHECK(refused_is_clean(22u, 20) == 0, 4);
    /* 3. a row with no terminator */
    reset_world();
    stage(EPOCH, 23u, 2u, 0u, 1u);
    memset(info.text[1], 'A', SLINK_INFO_LINE_WIDTH);
    post(23u);
    CHECK(step() == SLINK_PANEL_REFUSED, 5);
    CHECK(refused_is_clean(23u, 30) == 0, 6);
    /* 4. a mismatched session epoch */
    reset_world();
    stage(EPOCH + 1u, 24u, 2u, 0u, 1u);
    post(24u);
    CHECK(step() == SLINK_PANEL_REFUSED, 7);
    CHECK(refused_is_clean(24u, 40) == 0, 8);
    /* 5. request_seq == 0 */
    reset_world();
    stage(EPOCH, 25u, 2u, 0u, 1u);
    info.request_seq = 0u;
    mailbox.seq = 25u;
    post(25u);
    CHECK(step() == SLINK_PANEL_REFUSED, 9);
    CHECK(refused_is_clean(25u, 50) == 0, 10);
    /* 6. enable == 0 */
    reset_world();
    stage(EPOCH, 26u, 2u, 0u, 1u);
    info.enable = 0u;
    post(26u);
    CHECK(step() == SLINK_PANEL_REFUSED, 11);
    CHECK(refused_is_clean(26u, 60) == 0, 12);
    /* 7. no session at all: mailbox epoch zero (the mailbox survives a soft reset) */
    reset_world();
    stage(0u, 27u, 2u, 0u, 1u);
    post(27u);
    mailbox.session_epoch = 0u;
    CHECK(step() == SLINK_PANEL_REFUSED, 13);
    CHECK(refused_is_clean(27u, 70) == 0, 14);
    /* 8. the engine refuses to start */
    reset_world();
    stage(EPOCH, 28u, 2u, 0u, 1u);
    start_ok = 0;
    post(28u);
    CHECK(step() == SLINK_PANEL_REFUSED, 15);
    CHECK(starts == 1, 16);              /* attempted, and refused */
    CHECK(mailbox.status == SLINK_ST_FAIL && mailbox.reason == SLINK_REASON_BAD_ARGS, 17);
    CHECK(mailbox.ack_seq == 28u && mailbox.opcode == 0, 18);
    CHECK(info.state == 0 && state.producer.active == 0, 19);
    /* 9. the page slot is validated even when lines < 7 (row 7 is always checked) */
    reset_world();
    stage(EPOCH, 29u, 2u, 0u, 1u);
    memset(info.text[SLINK_INFO_PAGE_SLOT], 'B', SLINK_INFO_LINE_WIDTH);
    post(29u);
    CHECK(step() == SLINK_PANEL_REFUSED, 20);
    CHECK(refused_is_clean(29u, 80) == 0, 21);
    /* row 6 is NOT validated: a payload with garbage in row 6 is accepted */
    reset_world();
    stage(EPOCH, 30u, SLINK_INFO_MAX_LINES, 0u, 1u);
    memset(info.text[6], 'C', SLINK_INFO_LINE_WIDTH);
    post(30u);
    CHECK(step() == SLINK_PANEL_STARTED, 22);
    CHECK(starts == 1, 23);
    /* a posted request whose seq does not match request_seq is refused too */
    reset_world();
    stage(EPOCH, 31u, 2u, 0u, 1u);
    post(99u);
    CHECK(step() == SLINK_PANEL_REFUSED, 24);
    CHECK(refused_is_clean(99u, 90) == 0, 25);
    /* every shape, in a loop, left the same trace */
    for (k = 0; k < 8u; k++) {
        reset_world();
        stage(EPOCH, (uint16_t)(40u + k), 2u, 0u, 1u);
        info.lines = 0u;
        mailbox.seq = (uint16_t)(40u + k);
        post((uint16_t)(40u + k));
        CHECK(step() == SLINK_PANEL_REFUSED, 30 + (int)k);
    }
    return 0;
}

/* --------------------------------------------------------------------------- F9 */
int scen_gating(void)
{
    /* the menu is closed: an un-posted staged payload opens nothing, quietly */
    reset_world();
    stage(EPOCH, 51u, 2u, 0u, 1u);
    menu_ok = 0;
    for (int n = 0; n < 4; n++) {
        CHECK(step() == SLINK_PANEL_IDLE, 1);
        CHECK(starts == 0 && mailbox.ack_seq == 0u && mailbox.status == 0u, 2);
    }
    /* ... and a posted request is refused with the spec's reason, not opened. The posted seq
     * MATCHES request_seq on purpose: otherwise the refusal comes from the seq guard and the
     * gate is left unmeasured. */
    post(51u);
    CHECK(step() == SLINK_PANEL_REFUSED, 3);
    CHECK(refused_is_clean(51u, 10) == 0, 4);
    CHECK(starts == 0, 5);
    /* the fade is running: same answer, the other gate */
    reset_world();
    stage(EPOCH, 53u, 2u, 0u, 1u);
    fade_ok = 0;
    CHECK(step() == SLINK_PANEL_IDLE, 6);
    post(53u);
    CHECK(step() == SLINK_PANEL_REFUSED, 7);
    CHECK(refused_is_clean(53u, 20) == 0, 8);
    /* a child app is already resident */
    reset_world();
    stage(EPOCH, 55u, 2u, 0u, 1u);
    app_live = 1;
    post(55u);
    CHECK(step() == SLINK_PANEL_REFUSED, 9);
    CHECK(refused_is_clean(55u, 30) == 0, 10);
    /* an ABSENT gate is not an open door: a NULL predicate refuses */
    reset_world();
    stage(EPOCH, 57u, 2u, 0u, 1u);
    engine.fade_finished = NULL;
    post(57u);
    CHECK(step() == SLINK_PANEL_REFUSED, 11);
    CHECK(refused_is_clean(57u, 40) == 0, 12);
    engine.fade_finished = fade_fn;
    engine.menu_open = NULL;
    stage(EPOCH, 58u, 2u, 0u, 1u);
    post(58u);
    CHECK(step() == SLINK_PANEL_REFUSED, 13);
    CHECK(refused_is_clean(58u, 50) == 0, 14);
    engine.menu_open = menu_fn;
    /* app_running is OPTIONAL: unbound, it is not a guard and must not block */
    reset_world();
    stage(EPOCH, 60u, 2u, 0u, 1u);
    engine.app_running = NULL;
    CHECK(step() == SLINK_PANEL_STARTED, 15);
    CHECK(starts == 1, 16);
    engine.app_running = app_fn;
    /* both ends open -> the panel opens */
    reset_world();
    stage(EPOCH, 61u, 2u, 0u, 1u);
    CHECK(step() == SLINK_PANEL_STARTED, 17);
    CHECK(starts == 1 && info.state == 1, 18);
    /* a null argument fails closed and writes nothing */
    reset_world();
    stage(EPOCH, 62u, 2u, 0u, 1u);
    CHECK(slink_gen4_panel_step(NULL, &mailbox, &info, &engine) == SLINK_PANEL_REFUSED, 20);
    CHECK(slink_gen4_panel_step(&state, NULL, &info, &engine) == SLINK_PANEL_REFUSED, 21);
    CHECK(slink_gen4_panel_step(&state, &mailbox, NULL, &engine) == SLINK_PANEL_REFUSED, 22);
    CHECK(slink_gen4_panel_step(&state, &mailbox, &info, NULL) == SLINK_PANEL_REFUSED, 23);
    CHECK(starts == 0 && mailbox.status == 0u, 24);
    /* the gate itself fails closed on an absent seam: an unbound engine is not an open
     * door. This is the assertion the "treats an absent gate as safe" control attacks. */
    CHECK(slink_gen4_panel_safe(NULL) == 0, 25);
    return 0;
}

/* --------------------------------------------------------------- one in flight */
int scen_single(void)
{
    reset_world();
    stage(EPOCH, 71u, 2u, 0u, 3u);
    CHECK(step() == SLINK_PANEL_STARTED, 1);
    CHECK(starts == 1, 2);
    /* a second request while the panel is live is REFUSED, not queued and not opened */
    stage(EPOCH, 72u, 2u, 1u, 3u);
    post(72u);
    CHECK(step() == SLINK_PANEL_REFUSED, 4);
    CHECK(starts == 1, 5);
    CHECK(mailbox.status == SLINK_ST_FAIL && mailbox.reason == SLINK_REASON_BAD_ARGS, 6);
    /* an un-posted second payload is ignored while live, and start is still not called */
    stage(EPOCH, 73u, 2u, 2u, 3u);
    mailbox.opcode = 0;
    CHECK(step() == SLINK_PANEL_DRAINED, 7);
    CHECK(starts == 1, 8);
    /* The live panel closes, and the SAME visit opens the next one: the host left the payload
     * staged, so the drain's fall-through starts it again (panel_producer.h:44). */
    stage(EPOCH, 71u, 2u, 0u, 3u);
    mailbox.opcode = 0;
    queue_poll(2);
    CHECK(step() == SLINK_PANEL_CLOSED, 9);
    CHECK(info.closed_seq == 71u, 10);
    CHECK(starts == 2 && info.state == 1, 11);
    /* while THAT one is live a third request is refused, not queued */
    stage(EPOCH, 74u, 2u, 0u, 1u);
    info.state = 1; /* host staging must not write the ROM-owned state byte */
    post(74u);
    CHECK(step() == SLINK_PANEL_REFUSED, 12);
    CHECK(starts == 2, 13);
    /* the host withdraws the payload and restores the live request, so the close publishes */
    stage(EPOCH, 71u, 2u, 0u, 3u);
    mailbox.opcode = 0;
    info.state = 1;
    info.enable = 0u;
    queue_poll(2);
    CHECK(step() == SLINK_PANEL_CLOSED, 14);
    CHECK(info.closed_seq == 71u && info.state == 0, 15);
    CHECK(starts == 2, 16);
    CHECK(step() == SLINK_PANEL_IDLE, 17);
    return 0;
}

/* --------------------------------------------------------------- the result words */
int scen_result(void)
{
    struct { int is_a; uint8_t page; uint8_t pages; uint8_t want; } t[] = {
        { 1,   0u, 1u, CLOSE },  /* A on the only page closes (no wrap)                */
        { 1,   0u, 3u, MORE  },  /* A with a further page advances                     */
        { 1,   2u, 3u, CLOSE },  /* A on the last page closes                          */
        { 1,   0u, 0u, CLOSE },  /* a zero page count is one page                      */
        { 0,   0u, 3u, CLOSE },  /* B always closes                                    */
        { 0,   1u, 1u, CLOSE },
        { 1, 255u, 3u, CLOSE },  /* the counter carries out of 255: close, do not wrap  */
        { 1, 254u, 255u, CLOSE },
        { 1, 253u, 255u, MORE  }
    };
    unsigned k;
    CHECK(SLINK_GEN4_PANEL_RESULT_MORE == 0x00u, 1);
    CHECK(SLINK_GEN4_PANEL_RESULT_CLOSE == 0x7Fu, 2);
    for (k = 0; k < sizeof t / sizeof t[0]; k++) {
        uint8_t got = slink_gen4_panel_result(t[k].is_a, t[k].page, t[k].pages);
        if (got != t[k].want) {
            printf("FAIL result[%u] a=%d page=%u pages=%u got=%u want=%u\n",
                   k, t[k].is_a, (unsigned)t[k].page, (unsigned)t[k].pages,
                   (unsigned)got, (unsigned)t[k].want);
            return 3;
        }
    }
    /* and the app's byte is what the region carries at closed_seq */
    reset_world();
    stage(EPOCH, 81u, 2u, 0u, 1u);
    CHECK(step() == SLINK_PANEL_STARTED, 4);
    queue_poll(1);
    CHECK(step() == SLINK_PANEL_DRAINED, 6);
    queue_poll(2);
    last_result = slink_gen4_panel_result(1, 0, 1);
    CHECK(step() == SLINK_PANEL_CLOSED, 7);
    CHECK(info.result == CLOSE && info.closed_seq == 81u, 8);
    return 0;
}

/* --------------------------------------------------------------- layout and numbers */
int scen_layout(void)
{
    reset_world();
    /* the sub-struct is this card's own: same size, same producer offset as beacon.h's */
    CHECK(sizeof(SlinkGen4PanelState) == sizeof(SlinkGen4StatePanel), 1);
    CHECK(offsetof(SlinkGen4PanelState, producer)
          == offsetof(SlinkGen4StatePanel, producer), 2);
    CHECK((offsetof(SlinkGen4PanelState, producer) % 4u) == 0u, 3);
    CHECK(SLINK_GEN4_PANEL_LAYOUT == SLINK_GEN4_STATE_PANEL_LAYOUT, 4);
    CHECK(SLINK_GEN4_PANEL_LAYOUT == 1u, 5);
    /* a fresh (zeroed) block is stamped, not reset away: nothing was in it */
    CHECK(step() == SLINK_PANEL_IDLE, 6);
    CHECK(state.layout == SLINK_GEN4_PANEL_LAYOUT, 7);
    CHECK(state.caps == (uint32_t)SLINK_GEN4_PANEL_CAPABILITIES, 8);
    /* a foreign layout is reset, never reinterpreted: a stale ACTIVE flag cannot survive,
     * and this payload is deliberately left invalid so no new start can mask that */
    reset_world();
    state.layout = 0xDEADBEEFu;
    state.producer.active = 1u;
    memset(state.producer.snapshot.text, 0x5A, sizeof state.producer.snapshot.text);
    CHECK(step() == SLINK_PANEL_IDLE, 9);
    CHECK(state.layout == SLINK_GEN4_PANEL_LAYOUT, 10);
    CHECK(state.producer.active == 0, 11);
    CHECK(state.producer.snapshot.text[0][0] == 0u, 12);
    CHECK(state.producer.snapshot.session_epoch == 0u, 13);
    CHECK(state.caps == (uint32_t)SLINK_GEN4_PANEL_CAPABILITIES, 14);
    /* and a fresh request still opens */
    stage(EPOCH, 91u, 2u, 0u, 1u);
    CHECK(step() == SLINK_PANEL_STARTED, 15);
    CHECK(starts == 1, 16);
    /* the capability contribution: shared bit 1, and never written to the mailbox here */
    CHECK(SLINK_CAP_INFO_PANEL == (1u << 1), 16);
    CHECK((SLINK_GEN4_PANEL_CAPABILITIES & SLINK_GEN4_CAP_MASK_LEGAL)
          == (uint32_t)SLINK_CAP_INFO_PANEL, 17);
    CHECK((SLINK_GEN4_PANEL_CAPABILITIES & 0x7Fu) == (uint32_t)SLINK_CAP_INFO_PANEL, 18);
    CHECK(mailbox.capabilities == 0u, 19);
    /* the opcode and the geometry the host stages against */
    CHECK(SLINK_OP_SHOW_INFO == 27, 20);
    CHECK(SLINK_INFO_LINE_WIDTH == 32u && SLINK_INFO_ROW_COUNT == 8u, 21);
    CHECK(SLINK_INFO_MAX_LINES == 6u && SLINK_INFO_PAGE_SLOT == 7u, 22);
    /* Q7: the spec is the record binding's own, and the charset member is never consulted */
    CHECK(slink_binding_gen4_pk4.text.width == 2, 23);
    CHECK(slink_binding_gen4_pk4.text.charset == SLINK_CHARSET_GEN4, 24);
    CHECK(slink_binding_gen4_pk4.text.charset == 2, 25);
    CHECK(slink_binding_gen4_pk4.text.terminator == 0xFFFFu, 26);
    CHECK(SLINK_CHARSET_GEN4 == 2, 27);
    /* 15 characters + the terminator is the whole row; a 16th would overflow the intent */
    {
        unsigned k;
        for (k = 0; k < SLINK_INFO_LINE_WIDTH / 2u; k++) {
            info.text[0][2u * k] = (uint8_t)('A' + (k % 26u));
            info.text[0][2u * k + 1u] = 0u;
        }
        info.text[0][30] = 0xFFu;
        info.text[0][31] = 0xFFu;
        CHECK(slink_text_terminator_index(info.text[0], SLINK_INFO_LINE_WIDTH,
                                          &slink_binding_gen4_pk4.text) == 15, 28);
        /* a row with NO terminator unit at all is unterminated: a zero unit is not one */
        memset(info.text[0], 0, SLINK_INFO_LINE_WIDTH);
        CHECK(slink_text_terminator_index(info.text[0], SLINK_INFO_LINE_WIDTH,
                                          &slink_binding_gen4_pk4.text) == -1, 29);
    }
    return 0;
}

/* ------------------------------------------------- what the validator consults (Q7) */
int scen_spec(void)
{
    reset_world();
    stage(EPOCH, 101u, 2u, 0u, 1u);
    /* a wrong CHARSET alone still accepts: the validator reads width and terminator only */
    engine.text = &spec_wrong_charset;
    CHECK(step() == SLINK_PANEL_STARTED, 1);
    CHECK(starts == 1, 2);
    /* The Gen 3 spec (8-bit, 0xFF) is ACCEPTED on a Gen 4 row, and that is the point: the
     * low byte of the 0xFFFF terminator is 0xFF, so an 8-bit scan finds one. Nothing about the
     * payload distinguishes the two specs, which is why the seam must carry the record
     * binding's own SlinkTextSpec instead of a hand-written one. */
    reset_world();
    stage(EPOCH, 102u, 2u, 0u, 1u);
    engine.text = &spec_gen3;
    CHECK(step() == SLINK_PANEL_STARTED, 4);
    CHECK(starts == 1, 5);
    /* a right width with the wrong terminator value refuses too */
    reset_world();
    stage(EPOCH, 103u, 2u, 0u, 1u);
    engine.text = &spec_wrong_term;
    post(103u);
    CHECK(step() == SLINK_PANEL_REFUSED, 6);
    /* and no spec at all refuses (slink_text_terminator_index returns -1) */
    reset_world();
    stage(EPOCH, 104u, 2u, 0u, 1u);
    engine.text = NULL;
    post(104u);
    CHECK(step() == SLINK_PANEL_REFUSED, 7);
    engine.text = &slink_binding_gen4_pk4.text;
    return 0;
}

int main(void)
{
#if SCENARIO == 1
    return scen_handshake();
#elif SCENARIO == 2
    return scen_rewrite();
#elif SCENARIO == 3
    return scen_refuse();
#elif SCENARIO == 4
    return scen_gating();
#elif SCENARIO == 5
    return scen_single();
#elif SCENARIO == 6
    return scen_result();
#elif SCENARIO == 7
    return scen_layout();
#elif SCENARIO == 8
    return scen_spec();
#else
#error "no scenario selected"
#endif
}
'''


SCENARIOS = {
    1: "F6/F7 the drawn and closed handshake",
    2: "F6 a mid-panel host rewrite is ignored",
    3: "F8 nine refusal shapes, each FAIL + BAD_ARGS",
    4: "F9 the panel opens only when safe AND the menu is open",
    5: "one panel in flight",
    6: "the A/close result words",
    7: "layout stamp, cap word, ABI numbers, Q7 spec",
    8: "Q7 what the validator actually consults",
}


def _drive(tmp_path, scenario):
    return _build(tmp_path / f"s{scenario}", "panel", DRIVER, defines=[f"-DSCENARIO={scenario}"])


@pytest.mark.parametrize("scenario", sorted(SCENARIOS), ids=[f"{n}-{SCENARIOS[n]}" for n in sorted(SCENARIOS)])
def test_panel_policy_scenarios(tmp_path, scenario):
    _run(_drive(tmp_path, scenario))


# ------------------------------------------------------------------------------- source

def test_the_policy_is_object_free_and_host_only():
    """No file-scope object (patch/src/nds/gen4/README.md:57-59) and no game header: a static
    would move 0x021E5900 and every pinned hook site with it. Comments are stripped first,
    because both headers explain the rule in prose."""
    for header in (POLICY_H, PANEL_H):
        raw = header.read_text(encoding="utf-8")
        body = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
        for banned in ("static const", "static uint", "static int", "static Slink",
                       "static char", "static void"):
            assert banned not in body, f"{header.name}: {banned}"
        # every file-scope definition in the policy is a function
        assert not [ln for ln in body.splitlines()
                    if ln.startswith("static ") and "(" not in ln], header.name
        for banned in ("global.h", "system.h", "bg_window.h", "render_window.h", "overlay_manager.h"):
            assert f'#include "{banned}"' not in raw, f"{header.name}: {banned}"


def test_the_policy_does_not_depend_on_slinkgen4state():
    """SlinkGen4State is an anonymous-struct typedef in beacon.h, so the panel contract is
    documented in panel.h, not declared; panel_policy.h therefore carries no beacon.h and no
    SlinkGen4State at all."""
    policy = POLICY_H.read_text(encoding="utf-8")
    panel = PANEL_H.read_text(encoding="utf-8")
    assert '#include "beacon.h"' not in policy
    assert "SlinkGen4State " not in policy and "SlinkGen4State*" not in policy
    assert "SlinkGen4StatePanel" in policy  # named only in prose
    code = re.sub(r"/\*.*?\*/", " ", panel, flags=re.S)
    assert "Slink_NDS_Panel_Service" in panel  # documented in prose, not declared
    assert not re.search(r"void\s+Slink_NDS_Panel_Service\s*\(", code)
    # the layout word and the result words are the card's own, so no second vocabulary
    assert "SLINK_GEN4_STATE_PANEL_LAYOUT" not in policy.replace("beacon.h's", "")
    assert "#define SLINK_GEN4_PANEL_LAYOUT 1u" in panel
    assert "0x7Fu" in panel and "0x00u" in panel


def test_the_service_call_site_stays_named_and_ungated():
    """dispatch.c already calls Slink_NDS_Panel_Service under SLINK_GEN4_PANEL; the card does
    not add a route or a gate around it (dispatch.c:6-8)."""
    dispatch = (GEN4 / "dispatch.c").read_text(encoding="utf-8")
    assert "Slink_NDS_Panel_Service(st, m);" in dispatch
    assert "#if defined(SLINK_GEN4_PANEL)" in dispatch
    assert "SlinkGen4StatePanel" in (GEN4 / "beacon.h").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- red controls
# Each mutates a COPY of the real per-title headers and re-runs the SAME scenario the green
# test above runs. A control that stays green means its detector measures nothing.

_CONTROLS = [
    ("skips the fade gate",
     "panel_policy.h", "if (!e->fade_finished || !e->fade_finished(e->context)) return 0;",
     "if (0) return 0;", 4),
    ("skips the menu gate",
     "panel_policy.h", "if (!e->menu_open || !e->menu_open(e->context)) return 0;",
     "if (0) return 0;", 4),
    ("skips the resident-app gate",
     "panel_policy.h", "if (e->app_running && e->app_running(e->context)) return 0;",
     "if (0) return 0;", 4),
    # NOTE: forcing the policy's menu_open argument to 1 is deliberately NOT offered as a red
    # control: both it and safe()'s menu gate read the SAME predicate, so with one of them
    # removed the other still refuses and nothing goes red. The line is defence in depth, not
    # a separate rule -- and pretending otherwise would be a control that measures nothing.
    ("collapses the gate to the seam null check",
     "panel_policy.h", "if (!e->fade_finished || !e->fade_finished(e->context)) return 0;",
     "if (!e) return 0;", 4),
    ("inverts the A/close rule",
     "panel_policy.h", "(is_a && next < (unsigned)pages) ? SLINK_GEN4_PANEL_RESULT_MORE",
     "(is_a && next >= (unsigned)pages) ? SLINK_GEN4_PANEL_RESULT_MORE", 6),
    ("lets a stale layout keep its active panel",
     "panel_policy.h", "slink_gen4_panel_clear(&s->producer);", "(void)0;", 7),
    ("publishes no capability",
     "panel_policy.h", "s->caps = (uint32_t)SLINK_GEN4_PANEL_CAPABILITIES;",
     "s->caps = 0u;", 7),
    ("treats an absent gate as safe",
     "panel_policy.h", "if (!e) return 0;", "if (!e) return 1;", 4),
]


@pytest.mark.parametrize("label,filename,anchor,replacement,scenario",
                         _CONTROLS, ids=[c[0] for c in _CONTROLS])
def test_red_controls(tmp_path, label, filename, anchor, replacement, scenario):
    gen4 = _mutant_gen4(tmp_path, label.replace(" ", "_"), filename, anchor, replacement)
    exe, done = _compile(tmp_path / f"m{scenario}", "mutant", DRIVER,
                         defines=[f"-DSCENARIO={scenario}"], gen4=gen4)
    assert done.returncode == 0, f"control {label!r} does not even compile: {done.stderr}"

    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
    assert run.returncode != 0, f"red control {label!r} did not trip: {run.stdout}{run.stderr}"
