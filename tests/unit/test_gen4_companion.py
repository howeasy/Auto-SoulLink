"""Gen 4 companion binder: committed beacon.h -> host-C arena images -> lua/gen4/companion.lua.

Every offset, size, field position, magic and capability value used here comes from the REAL
committed headers (`patch/src/nds/common/abi.h`, `patch/src/nds/gen4/beacon.h`) compiled for
the host by a C harness that stamps images in the ROM's own publish order (payload first,
magic LAST -- beacon.c:195-210). The module under test is the shipped `lua/gen4/companion.lua`;
the reader it binds is the shipped `lua/nds/mailbox.lua`. The memory reader is a boundary
simulation (a mutable byte buffer with injected faults), the way the mailbox test's is.

The helpers `_gcc` and the discovery contract are COPIED from tests/unit/test_nds_mailbox.py
rather than imported: that module owns its own skip reason (`NDS_MAILBOX_HOST_CC_ABSENT`) and
its own fixtures, and one test module importing another's helpers makes one gate fail under
the other's name. Everything else here is this card's own.

One convention note, because it is a trap: lupa does not bind `self` for an attribute call,
so `binder.poll(prev)` would drop the self argument a `:method` needs. Every method call in
this file goes through `lua_method`, which invokes it FROM LUA as `o:name(...)` -- the syntax
production uses -- so no caller convention is guessed here.
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

# Host-gcc probe binaries must never raise a Windows WER/GPF dialog: it blocks an unattended
# run forever. SetErrorMode is inherited by every child exe this module starts.
if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x8003)
COMMON = ROOT / "patch/src/nds/common"
GEN4 = ROOT / "patch/src/nds/gen4"
BEACON = GEN4 / "beacon.c"
MODULE = ROOT / "lua/gen4/companion.lua"
MAILBOX = ROOT / "lua/nds/mailbox.lua"
BASE = 0x02468000  # arbitrary fake-memory address, not a game address


def _gcc():
    # Same discovery contract as test_nds_mailbox.py / test_nds_native_witness.py.
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
    reason = "NDS_GEN4_COMPANION_HOST_CC_ABSENT: set SLINK_HOST_GCC; C-to-Lua integration did not run"
    if os.environ.get("SLINK_REQUIRE_HOST_CC") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


HARNESS = r'''
#include "abi.h"
#include "beacon.h"
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The host reader's premise, compiled rather than assumed: the block is 64 bytes at the
   ABI's reserved offset, and the header's own FIELD macros agree with the struct. */
_Static_assert(SLINK_GEN4_TITLE_OFFSET == SLINK_RESERVED_OFFSET, "title block starts at the reserved region");
_Static_assert(sizeof(SlinkGen4Title) == SLINK_GEN4_TITLE_SIZE, "title size");
_Static_assert(offsetof(SlinkGen4Title, magic) == 0u, "magic");
_Static_assert(offsetof(SlinkGen4Title, version) == 4u, "version");
_Static_assert(offsetof(SlinkGen4Title, size) == 6u, "size");
_Static_assert(offsetof(SlinkGen4Title, reserved) == 28u, "headroom tail");
_Static_assert(offsetof(SlinkGen4Title, cookie) == SLINK_GEN4_TITLE_COOKIE_FIELD, "cookie field macro");
_Static_assert(offsetof(SlinkGen4Title, identity) == SLINK_GEN4_TITLE_IDENTITY_FIELD, "identity field macro");
_Static_assert(offsetof(SlinkGen4Title, delta) == SLINK_GEN4_TITLE_DELTA_FIELD, "delta field macro");
_Static_assert(offsetof(SlinkGen4Title, generation) == SLINK_GEN4_TITLE_GENERATION_FIELD, "generation field macro");
_Static_assert(offsetof(SlinkGen4Title, registrations) == SLINK_GEN4_TITLE_REGISTRATIONS_FIELD, "registrations field macro");

static unsigned char arena[SLINK_ARENA_SIZE];

struct stamp {
  unsigned magic, version, size, cookie, identity, delta, generation, registrations;
};

/* beacon.c:195-210 (Slink_NDS_Publish): payload first, then size, then version, and magic
   LAST, so a host sampling mid-visit sees a valid header over a stale payload rather than
   a valid header over a torn one. That order is the reason the binder copies the block
   twice around a check. */
static void publish(volatile SlinkGen4Title *t, const struct stamp *s) {
  t->cookie = s->cookie;
  t->identity = s->identity;
  t->delta = s->delta;
  t->generation = s->generation;
  t->registrations = s->registrations;
  t->size = (uint16_t)s->size;
  t->version = (uint16_t)s->version;
  t->magic = s->magic;
}

static unsigned opt(int argc, char **argv, const char *name, unsigned fallback) {
  size_t n = strlen(name);
  for (int i = 1; i < argc; i++) {
    if (strncmp(argv[i], name, n) == 0 && argv[i][n] == '=') {
      return (unsigned)strtoul(argv[i] + n + 1, NULL, 0);
    }
  }
  return fallback;
}

static void layout(void) {
#define VALUE(k,v) printf("%s=%u\n", k, (unsigned)(v))
#define REL(f) VALUE("title_" #f "_rel", offsetof(SlinkGen4Title, f))
#define ABS(f) VALUE("title_" #f, SLINK_GEN4_TITLE_OFFSET + offsetof(SlinkGen4Title, f))
  VALUE("arena_size", SLINK_ARENA_SIZE);
  VALUE("reserved_offset", SLINK_RESERVED_OFFSET);
  VALUE("title_offset", SLINK_GEN4_TITLE_OFFSET);
  VALUE("title_size", SLINK_GEN4_TITLE_SIZE);
  VALUE("title_magic", SLINK_GEN4_TITLE_MAGIC);
  VALUE("title_version", SLINK_GEN4_TITLE_VERSION);
  REL(magic); REL(version); REL(size); REL(reserved);
  REL(cookie); REL(identity); REL(delta); REL(generation); REL(registrations);
  ABS(cookie); ABS(identity); ABS(delta); ABS(generation); ABS(registrations);
  VALUE("title_cookie_field", SLINK_GEN4_TITLE_COOKIE_FIELD);
  VALUE("title_identity_field", SLINK_GEN4_TITLE_IDENTITY_FIELD);
  VALUE("title_delta_field", SLINK_GEN4_TITLE_DELTA_FIELD);
  VALUE("title_generation_field", SLINK_GEN4_TITLE_GENERATION_FIELD);
  VALUE("title_registrations_field", SLINK_GEN4_TITLE_REGISTRATIONS_FIELD);
  VALUE("mailbox_signature", offsetof(SlinkMailboxV2, signature));
  VALUE("mailbox_capabilities", offsetof(SlinkMailboxV2, capabilities));
  VALUE("mailbox_session_epoch", offsetof(SlinkMailboxV2, session_epoch));
  VALUE("mailbox_reserved", offsetof(SlinkMailboxV2, reserved));
  VALUE("caps_shared", SLINK_CAP_MATCH_CALL * 2u - 1u);
  VALUE("caps_reserved", 0xFF80u & ~((SLINK_CAP_MATCH_CALL * 2u) - 1u));
  VALUE("caps_title", SLINK_GEN4_CAP_MASK_TITLE);
}

int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "layout")) { layout(); return 0; }

  for (unsigned i = 0; i < SLINK_ARENA_SIZE; i++) arena[i] = (unsigned char)(i * 7u + 3u);

  SlinkMailboxV2 *m = (SlinkMailboxV2 *)(void *)arena;
  volatile SlinkGen4Title *t = (SlinkGen4Title *)(void *)(arena + SLINK_GEN4_TITLE_OFFSET);
  unsigned char *headroom = (unsigned char *)(void *)(arena + SLINK_GEN4_TITLE_OFFSET);

  m->signature = SLINK_SIGNATURE;
  m->abi_version = (uint16_t)SLINK_ABI_VERSION;
  m->capabilities = opt(argc, argv, "--capabilities", SLINK_GEN4_CAPABILITIES);
  m->session_epoch = opt(argc, argv, "--epoch", 9u);
  m->producer_phase = (uint8_t)opt(argc, argv, "--phase", SLINK_PHASE_IDLE);
  m->status = SLINK_ST_OK;
  m->reserved = opt(argc, argv, "--envelope-generation", 4u); /* the session epoch mirror */

  struct stamp s;
  s.magic = opt(argc, argv, "--title-magic", SLINK_GEN4_TITLE_MAGIC);
  s.version = opt(argc, argv, "--title-version", SLINK_GEN4_TITLE_VERSION);
  s.size = opt(argc, argv, "--title-size", (unsigned)sizeof(SlinkGen4Title));
  s.cookie = opt(argc, argv, "--cookie", 0xDEADBEEFu);
  s.identity = opt(argc, argv, "--identity", 0x11223344u);
  s.delta = opt(argc, argv, "--delta", 0x240u);
  s.generation = opt(argc, argv, "--generation", 4u);
  s.registrations = opt(argc, argv, "--registrations", 2u);
  memset((void *)(arena + SLINK_GEN4_TITLE_OFFSET), 0, SLINK_GEN4_TITLE_SIZE); /* declared reserved tail stays zero */
  publish(t, &s);

  headroom[SLINK_GEN4_TITLE_SIZE - 1u] = (unsigned char)opt(argc, argv, "--headroom", 0u);

  fputs("ARENA ", stdout);
  for (unsigned i = 0; i < SLINK_ARENA_SIZE; i++) printf("%02x", (unsigned)arena[i]);
  puts("");
  return 0;
}
'''

READERS = ("read_bytes", "read_u8", "read_u16", "read_u32")
FORMS = {"bytes": ("read_bytes",), "u8": ("read_u8",), "bytes_u32": ("read_bytes", "read_u32")}


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("nds-gen4-companion-host")
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


def _run(exe, *args):
    done = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def compiled(harness):
    return {name: int(value) for name, value in
            (line.split("=") for line in _run(harness, "layout").splitlines())}


@pytest.fixture(scope="module")
def image(harness):
    return bytes.fromhex(_run(harness).split()[1])


def stamped(harness, **overrides):
    """A fresh arena image with the named header/title fields overridden."""
    parts = _run(harness, *[f"--{name.replace('_', '-')}={hex(value)}" for name, value in overrides.items()])
    assert parts.startswith("ARENA ")
    return bytes.fromhex(parts.split()[1])


# ------------------------------------------------------------------ Lua plumbing

def lua_method(lua, obj, name):
    """`obj:name(...)` invoked FROM LUA, so lupa never has to guess the self convention."""
    return lua.eval("function(o) return function(...) return o:" + name + "(...) end end")(obj)


def two(result):
    """A Lua `return a, nil` arrives as a 1- or 2-tuple; normalise it to exactly two."""
    if not isinstance(result, tuple):
        return result, None
    if len(result) == 1:
        return result[0], None
    return result[0], result[1]


def to_dict(table):
    if not hasattr(table, "items"):
        return table
    return {key: to_dict(value) for key, value in table.items()}


class Rig:
    """A live binder over a mutable arena image, driven one poll at a time.

    `flip` is (arena offset, nth read of a chunk covering it): that read returns a flipped
    byte, which is how a tear between the two title copies is injected. The reader cannot
    see one, because the mailbox has no revision counter over the title block.
    """

    def __init__(self, compiled, data, *, source=None, form="bytes", flip=None, **config):
        self.compiled = compiled
        self.data = bytearray(data)
        self.counts = dict.fromkeys(READERS, 0)
        self.seen = {}
        self.flip = flip
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.globals_before = set(self.lua.globals().keys())
        self.shared = self.lua.execute(MAILBOX.read_text(encoding="utf-8"))
        self.module = self.lua.execute(
            source if source is not None else MODULE.read_text(encoding="utf-8"))
        names = FORMS[form]

        def scalar(address, width, name):
            self.counts[name] += 1
            return int.from_bytes(self.data[address - BASE:address - BASE + width], "little")

        def read_bytes(address, n):
            self.counts["read_bytes"] += 1
            start = address - BASE
            chunk = bytearray(self.data[start:start + n])
            if self.flip is not None and start <= self.flip[0] < start + n:
                self.seen[start] = self.seen.get(start, 0) + 1
                if self.seen[start] == self.flip[1]:
                    chunk[self.flip[0] - start] ^= 0xFF
            return self.lua.table_from(list(chunk))

        def read_u8(address):
            self.counts["read_u8"] += 1
            return self.data[address - BASE]

        supplied = {"read_bytes": read_bytes, "read_u8": read_u8,
                    "read_u16": lambda a: scalar(a, 2, "read_u16"),
                    "read_u32": lambda a: scalar(a, 4, "read_u32")}
        self.io = self.lua.table_from({name: supplied[name] for name in names})
        self.config = self.lua.table_from({"base": BASE, "mailbox": self.shared} | config)
        self.binder, self.reason = two(self.module.new(self.io, self.config))
        self.poll = lua_method(self.lua, self.binder, "poll") if self.binder is not None else None
        self.layout = lua_method(self.lua, self.binder, "layout") if self.binder is not None else None

    # -- arena edits
    def put(self, offset, value, width=4):
        self.data[offset:offset + width] = int(value).to_bytes(width, "little")

    def put_title(self, field, value, width=4):
        # compiled["title_magic"]/["title_version"] are CONSTANTS, not offsets; the header
        # words sit at the block base (beacon.h:86-89)
        header = {"magic": (0, 4), "version": (4, 2), "size": (6, 2)}
        if field in header:
            at, width = header[field]
            self.put(self.compiled["title_offset"] + at, value, width)
        else:
            self.put(self.compiled["title_" + field], value, width)

    def put_envelope(self, field, value, width=4):
        self.put(self.compiled["mailbox_" + field], value, width)

    def delta(self):
        at = self.compiled["title_delta"]
        return int.from_bytes(self.data[at:at + 4], "little")

    # -- driving
    def go(self, previous=None):
        state, reason = two(self.poll(self.lua.table_from(previous) if previous is not None else None))
        return to_dict(state), reason

    def tick(self):
        """One service visit's worth of clock: the engine delta advances (beacon.c:242-244)."""
        self.put_title("delta", self.delta() + 0x10)
        return self.delta()


def rig(compiled, image, **kwargs):
    made = Rig(compiled, image, **kwargs)
    assert made.binder is not None and made.reason is None, made.reason
    return made


def live(made, polls, previous=None):
    """Coherent polls with the engine clock advancing; returns the states and the state."""
    seen = []
    for _ in range(polls):
        made.tick()
        previous, reason = made.go(previous)
        assert reason is None, reason
        seen.append(previous["state"])
    return seen, previous


# ------------------------------------------------------------------ layout oracle

def test_layout_is_the_compiled_header_and_title_offset_is_derived(harness, compiled, image):
    made = rig(compiled, image)
    layout = to_dict(made.layout())
    assert layout["title_size"] == compiled["title_size"] == 0x40
    assert layout["title_magic"] == compiled["title_magic"] == 0x34474C53
    assert layout["title_version"] == compiled["title_version"] == 1
    for field in ("cookie", "identity", "delta", "generation", "registrations"):
        assert layout["title_" + field + "_field"] == compiled["title_" + field + "_field"]
    # beacon.h:75 derives the block from the ABI's reserved offset, and so does the binder
    # (from the shared reader's own layout), so the two headers cannot drift apart.
    assert layout["title_offset"] == compiled["title_offset"] == compiled["reserved_offset"]
    assert layout["caps_shared_mask"] == compiled["caps_shared"] == 0x7F
    assert layout["caps_reserved_mask"] == compiled["caps_reserved"] == 0xFF80
    assert layout["caps_title_mask"] == compiled["caps_title"] == 0xFFFF0000
    # the static half carries no title_offset: that offset is DERIVED per binder from the
    # shared reader, never a second copy of the ABI constant in this file
    static = to_dict(made.module.layout())
    assert "title_offset" not in static
    assert set(static) < set(layout) and all(layout[key] == value for key, value in static.items())
    # a fresh copy: mutating what layout() returned must not retarget the binder
    layout["title_size"] = 8
    assert to_dict(made.layout())["title_size"] == 0x40


def test_field_offsets_follow_beacon_h(compiled):
    # C2_BEACON_SPEC.md:148-152 and beacon.h:86-96 agree: cookie/identity/delta/generation/
    # registrations at +0x08/+0x0C/+0x10/+0x14/+0x18. (Spec :474 is the ABSOLUTE-address row,
    # not a block-relative table.) A reader that assumed the block base was the first field
    # would decode the wrong words, so the compiled offsets are pinned here.
    assert (compiled["title_cookie_rel"], compiled["title_identity_rel"],
            compiled["title_delta_rel"], compiled["title_generation_rel"],
            compiled["title_registrations_rel"]) == (8, 12, 16, 20, 24)
    assert compiled["title_offset"] == compiled["reserved_offset"] == 0xE00


# ------------------------------------------------------------------ decoding

def test_poll_decodes_every_published_field(harness, compiled, image):
    made = rig(compiled, image)
    state, reason = made.go()
    assert reason is None and state["state"] == "WARMING"
    assert state["title"] == {"magic": 0x34474C53, "version": 1, "size": 0x40,
                              "cookie": 0xDEADBEEF, "identity": 0x11223344, "delta": 0x240,
                              "generation": 4, "registrations": 2, "headroom_zero": True}
    # the mailbox's own words, untouched; the coherence check proves these two agree
    assert state["generation"] == 4 == state["title"]["generation"]
    assert state["session_epoch"] == 9 and state["producer_phase"] == 0
    assert state["caps"] == {"word": 0, "shared": 0, "reserved": 0, "title_private": 0}


def test_capability_bits_are_reported_whole_and_split(harness, compiled, image):
    for caps in (0, 1, 0x80, 0xFFFF0000, 0xFFFFFFFF, 0x000F0081):
        made = rig(compiled, stamped(harness, capabilities=caps))
        state, reason = made.go()
        assert reason is None, (caps, reason)
        assert state["capabilities"] == caps == state["caps"]["word"]
        assert state["caps_shared"] == caps & 0x7F
        assert state["reserved_bits"] == caps & 0xFF80
        assert state["caps"]["title_private"] == caps & 0xFFFF0000


def test_headroom_is_reported_and_never_gated(harness, compiled, image):
    made = rig(compiled, stamped(harness, headroom=0x5A))
    state, reason = made.go()
    assert reason is None and state["title"]["headroom_zero"] is False
    # a dirty tail is not a liveness event: the machine still reaches LIVE over it
    states, _ = live(made, 3, state)
    assert states == ["WARMING", "LIVE", "LIVE"]  # first poll above was stable 1, so K=3 lands on the 2nd tick


def test_one_poll_is_one_payload_copy_and_two_title_copies(compiled, image):
    made = rig(compiled, image)
    made.go()
    # bytes-only form: every scalar is its own 2/4-byte block read: 3 envelope samples x 6
    # scalars, plus the 80-byte payload and two 64-byte title copies
    assert made.counts == {"read_bytes": 3 * 6 + 1 + 2, "read_u8": 0, "read_u16": 0, "read_u32": 0}
    # bytes+u32 form: 3 envelope samples of (5 u32 + one 2-byte abi composed from bytes),
    # plus the 80-byte payload and two 64-byte title copies
    made = rig(compiled, image, form="bytes_u32")
    made.go()
    assert made.counts == {"read_bytes": 6, "read_u8": 0, "read_u16": 0, "read_u32": 15}
    # u8-only form: 3 x 22 envelope bytes + 80 payload bytes + 2 x 64 title bytes
    made = rig(compiled, image, form="u8")
    made.go()
    assert made.counts == {"read_bytes": 0, "read_u8": 3 * 22 + 80 + 2 * 0x40,
                           "read_u16": 0, "read_u32": 0}


# ------------------------------------------------------------------ liveness

def test_first_poll_is_warming_and_live_lands_after_exactly_k_polls(compiled, image):
    made = rig(compiled, image, stable_polls=3, stall_polls=2)
    first, reason = made.go()
    assert reason is None and first["state"] == "WARMING" and first["stable"] == 1
    states, state = live(made, 2, first)
    assert states == ["WARMING", "LIVE"] and state["stable"] == 3
    states, state = live(made, 2, state)
    assert states == ["LIVE", "LIVE"]


def test_thresholds_are_per_title_and_the_shared_defaults_are_not_enforced(compiled, image):
    made = rig(compiled, image, stable_polls=5, stall_polls=4)
    assert to_dict(made.layout())["stable_polls"] == 5
    states, state = live(made, 5)
    assert states == ["WARMING"] * 4 + ["LIVE"], states
    # four polls without the clock advancing is this title's budget, not the shared default 2
    for expected in range(1, 4):
        state, reason = made.go(state)
        assert (reason, state["state"], state["stalled"]) == (None, "WARMING", expected)
    state, reason = made.go(state)
    assert (reason, state["state"]) == (None, "LOST")


def test_a_generation_change_is_lost_then_warming_again(compiled, image):
    made = rig(compiled, image)
    states, state = live(made, 3)
    assert states[-1] == "LIVE"
    # a soft reset: the ROM re-mints the cookie and bumps the generation in one block
    # (beacon.c:174-193) and restarts its own delta from 0 in the same breath
    made.put_title("generation", 5)
    made.put_envelope("reserved", 5)
    made.put_title("cookie", 0xFEEDFACE)
    made.put_title("delta", 0)
    state, reason = made.go(state)
    assert reason is None and state["state"] == "LOST" and state["stable"] == 0
    states, state = live(made, 3, state)
    assert states == ["WARMING", "WARMING", "LIVE"]


def test_the_latch_delta_reset_is_the_latch_and_not_a_stall_tick(compiled, image):
    made = rig(compiled, image)
    _, state = live(made, 3)
    made.put_title("generation", 5)
    made.put_envelope("reserved", 5)
    made.put_title("cookie", 0xFEEDFACE)
    made.put_title("delta", 0)
    state, reason = made.go(state)
    # the reset that came WITH the generation change consumed no stall budget
    assert (reason, state["state"], state["stalled"]) == (None, "LOST", 0)
    again, reason = made.go(state)
    # one further poll at the same delta is the FIRST stall tick, which is not yet a LOST
    assert (reason, again["state"], again["stalled"]) == (None, "WARMING", 1)
    third, reason = made.go(again)
    assert (reason, third["state"]) == (None, "LOST")


def test_a_stalled_clock_for_n_polls_is_lost_and_resumes_from_warming(compiled, image):
    made = rig(compiled, image, stall_polls=2)
    states, state = live(made, 3)
    assert states[-1] == "LIVE"
    # the arena stopped being re-stamped: the engine delta does not advance
    first, reason = made.go(state)
    assert (reason, first["state"], first["stalled"]) == (None, "WARMING", 1)
    second, reason = made.go(first)
    assert (reason, second["state"]) == (None, "LOST")
    states, state = live(made, 3, second)
    assert states == ["WARMING", "WARMING", "LIVE"]


def test_a_cookie_change_alone_is_lost(compiled, image):
    made = rig(compiled, image)
    _, state = live(made, 3)
    made.put_title("cookie", 0x0BADF00D)
    state, reason = made.go(state)
    assert reason is None and state["state"] == "LOST"
    assert state["stable_cookie"] == 0x0BADF00D and state["stable_generation"] == 4


def test_a_refused_poll_drops_liveness_and_the_next_good_poll_rewarms(compiled, image):
    made = rig(compiled, image)
    _, state = live(made, 3)
    assert state["state"] == "LIVE"
    made.put_title("magic", 0x12345678)
    refused, reason = made.go(state)
    assert reason == "title:magic" and refused["state"] == "LOST"
    assert refused["stable"] == 0 and "title" not in refused
    made.put_title("magic", 0x34474C53)
    made.tick()
    again, reason = made.go(refused)
    assert reason is None and again["state"] == "WARMING" and again["stable"] == 1


def test_capabilities_never_gate_liveness(harness, compiled, image):
    # At C2 the advertised set is 0 (C2_BEACON_SPEC.md:432-442): a host that required any
    # capability bit could never come live at all, so the two extremes must both go LIVE.
    for caps in (0, 0xFFFF0000, 0xFFFFFFFF, 0x00000080):
        made = rig(compiled, stamped(harness, capabilities=caps))
        states, _ = live(made, 3)
        assert states == ["WARMING", "WARMING", "LIVE"], (caps, states)


# ------------------------------------------------------------------ refusals

@pytest.mark.parametrize("override,reason", [
    ({"title_magic": 0x12345678}, "title:magic"),
    ({"title_magic": 0}, "title:magic"),
    ({"title_magic": 0x34474C54}, "title:magic"),
    ({"title_version": 0}, "title:version"),
    ({"title_version": 2}, "title:version"),
    ({"title_size": 0}, "title:size"),
    ({"title_size": 0x3C}, "title:size"),
    ({"title_size": 0x80}, "title:size"),
    ({"envelope_generation": 9}, "title:coherence"),  # title.generation != mailbox reserved
    ({"phase": 6}, "mailbox:phase")  # 5 (uncertain) is the last valid phase,
])
def test_refusals_are_named(harness, compiled, image, override, reason):
    made = rig(compiled, stamped(harness, **override))
    state, actual = made.go()
    assert actual == reason, (override, actual)
    assert state is None or state["state"] == "LOST"


def test_a_torn_title_is_refused_rather_than_decoded(compiled, image):
    # The block is outside the witness revision protocol, so the tear is injected at the
    # memory boundary: the second copy of the block differs from the first.
    for field in ("magic", "delta", "registrations"):  # a torn header word, payload word, tail
        offset = compiled["title_offset"] if field == "magic" else compiled["title_" + field]
        for nth in (1, 2):
            made = rig(compiled, image, flip=(offset, nth))
            state, reason = made.go()
            assert reason == "title:coherence", (field, nth, reason)
            assert state["state"] == "LOST"


def test_a_corrupt_envelope_is_refused_before_the_title_is_decoded(compiled, image):
    made = rig(compiled, image)
    made.put_envelope("signature", 0)
    state, reason = made.go()
    assert reason == "mailbox:signature" and state["state"] == "LOST"
    # a binder aimed outside the image cannot decode anything either
    made = rig(compiled, image, base=BASE + 0x100000)
    state, reason = made.go()
    assert reason in ("mailbox:signature", "read:error"), reason
    assert state["state"] == "LOST"


# ------------------------------------------------------------------ purity

def test_step_is_pure_and_usable_without_a_binder(compiled, image):
    made = rig(compiled, image)
    sample = made.go()[0]
    previous = {"state": "LIVE", "stable": 3, "stalled": 0, "stable_generation": 4,
                "stable_cookie": 0xDEADBEEF, "stable_delta": 0x100, "marker": "keep"}
    snapshot = dict(previous)
    lua, step = made.lua, made.module.step
    again = to_dict(step(lua.table_from(previous), lua.table_from(sample, recursive=True),
                         lua.table_from({"stable_polls": 3, "stall_polls": 2})))
    assert previous == snapshot, "step must not mutate the caller's table"
    assert again["state"] == "LIVE" and again["stable"] == 4  # the clock moved on this poll
    # A K-walk straight through step, with no binder in the loop: the threshold that reaches
    # LIVE is the one passed in, never the shared default.
    def walk(stable_polls, polls=None):
        seen, prev = [], None
        for i in range(polls if polls is not None else stable_polls):
            sample_in = {"generation": 4,
                         "title": {"cookie": 0xDEADBEEF, "delta": 0x100 + i * 0x10}}
            prev = to_dict(step(lua.table_from(prev, recursive=True) if prev is not None else None,
                                lua.table_from(sample_in, recursive=True),
                                lua.table_from({"stable_polls": stable_polls, "stall_polls": 4})))
            seen.append(prev["state"])
        return seen

    # K=1 still needs one observed clock advance, which the first sample cannot show
    assert walk(1, 2) == ["WARMING", "LIVE"]
    assert walk(3) == ["WARMING", "WARMING", "LIVE"]
    assert walk(5) == ["WARMING"] * 4 + ["LIVE"]
    assert walk(3, 6) == ["WARMING", "WARMING", "LIVE", "LIVE", "LIVE", "LIVE"]
    assert to_dict(step(None, None, lua.table_from({})))["state"] == "LOST"
    assert to_dict(step(None, lua.table_from({"generation": 4}), lua.table_from({})))["state"] == "LOST"
    assert to_dict(step(None, lua.table_from({"generation": 4, "title": {}}, recursive=True), lua.table_from({})))["state"] == "LOST"


def test_configuration_is_validated_and_copied(compiled, image):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(MODULE.read_text(encoding="utf-8"))
    shared = lua.execute(MAILBOX.read_text(encoding="utf-8"))
    io = lua.table_from({"read_bytes": lambda a, n: lua.table_from(list(image[a - BASE:a - BASE + n]))})
    for change, reason in (({"mailbox": None}, "config:mailbox"),
                           ({"mailbox": lua.table_from({"new": 1})}, "config:mailbox"),
                           ({"stable_polls": 0}, "config:polls"),
                           ({"stable_polls": -1}, "config:polls"),
                           ({"stable_polls": 1.5}, "config:polls"),
                           ({"stable_polls": "3"}, "config:polls"),
                           ({"stall_polls": 0}, "config:polls"),
                           ({"base": -1}, "config:base"),
                           ({"base": "0x100"}, "config:base")):
        obj, why = two(module.new(io, lua.table_from({"base": BASE, "mailbox": shared} | change)))
        assert obj is None and why == reason, (change, why)
    # a later mutation of the caller's config must not retarget or re-threshold a live binder
    config = lua.table_from({"base": BASE, "mailbox": shared, "stable_polls": 3, "stall_polls": 2})
    obj, why = two(module.new(io, config))
    assert obj is not None and why is None
    config["base"] = BASE + 0x100000
    config["stable_polls"] = 99
    assert to_dict(lua_method(lua, obj, "layout")(None))["stable_polls"] == 3
    state, reason = two(lua_method(lua, obj, "poll")(None))
    assert reason is None and to_dict(state)["title"]["cookie"] == 0xDEADBEEF


def test_no_globals_are_created(compiled, image):
    made = rig(compiled, image)
    assert set(made.lua.globals().keys()) == made.globals_before
    live(made, 2)
    assert set(made.lua.globals().keys()) == made.globals_before


def code_only(source):
    """The source with every `--` comment stripped, so the guards below see CODE only."""
    return "\n".join(line.split("--")[0] for line in source.splitlines())


# The only 7-8 hex-digit literals allowed in CODE: the title magic (beacon.h:78, checked
# against the compiled header by test_layout_is_the_compiled_header) and the u32 mask.
ALLOWED_HEX = {"0x34474C53", "0xFFFFFFFF"}


def assert_no_address_or_domain(source):
    code = code_only(source)
    found = {literal for literal in re.findall(r"0x[0-9A-Fa-f]+", code) if len(literal) - 2 in (7, 8)}
    assert not found - ALLOWED_HEX, sorted(found - ALLOWED_HEX)
    for domain in ("Instruction TCM", "ARM9 System Bus", "ARM9 r15", "01FFEC00", "6C00"):
        assert domain not in code, domain
    for absent in ("memory.", "emu.", "event.", "joypad", "os.", "io.open", "write",
                   "framecount", "require", "dofile"):
        assert absent not in code, absent


def test_the_module_names_no_address_and_no_domain_string():
    source = MODULE.read_text(encoding="utf-8")
    assert_no_address_or_domain(source)
    # ...and the domain rule it exists to enforce is written down where a caller will read it
    for documented in ("Instruction TCM", "01FFEC00", "ITCM", "Client.PLATFORM", "mailbox"):
        assert documented in source, documented
    # positive controls: an address or a domain literal in code must go red
    with pytest.raises(AssertionError):
        assert_no_address_or_domain(source + "\nlocal INJECTED = 0x01FFEC00\n")
    with pytest.raises(AssertionError):
        assert_no_address_or_domain(source + '\nlocal INJECTED = "Instruction TCM"\n')
    with pytest.raises(AssertionError):
        assert_no_address_or_domain(source + "\nlocal INJECTED = memory.write_u8(0, 0)\n")


def test_step_cannot_read_a_capability_bit():
    code = code_only(MODULE.read_text(encoding="utf-8"))
    body = code.split("function Companion.step", 1)[1].split("function Companion.new", 1)[0]
    for absent in ("caps", "capabilities", "caps_shared", "reserved_bits", "title_private"):
        assert absent not in body, absent


# ------------------------------------------------------------------ red controls

COHERENCE = """        if not identical(first, second, L.title_size) then
            return refuse("title:coherence")
        end
"""

# The latch falls through to the clock block instead of returning, so the delta that reset
# WITH the generation change is counted as a stall tick.
LATCH_FALLTHROUGH = """        previous = { state = "LOST", stable = 0, stalled = 0,
                      stable_generation = generation, stable_cookie = cookie, stable_delta = delta }
"""

CAPS_GATE_OLD = "        local mid, mid_why = reader:header()\n"
CAPS_GATE_NEW = """        local mid, mid_why = reader:header()
        if mid.capabilities == 0 then return refuse("title:capabilities") end
"""


def test_revert_control_dropping_the_two_copy_coherence_check_is_caught(compiled, image):
    source = MODULE.read_text(encoding="utf-8")
    assert source.count(COHERENCE) == 1

    def torn(text):
        made = rig(compiled, image, source=text, flip=(compiled["title_delta"], 2))
        state, reason = made.go()
        assert (reason, state["state"]) == ("title:coherence", "LOST"), reason

    torn(source)
    with pytest.raises(AssertionError):
        torn(source.replace(COHERENCE, ""))


def test_revert_control_using_capabilities_as_a_gate_is_caught(compiled, image):
    source = MODULE.read_text(encoding="utf-8")
    assert source.count(CAPS_GATE_OLD) == 1

    def reaches_live(text):
        made = rig(compiled, image, source=text)
        states, _ = live(made, 3)
        assert states == ["WARMING", "WARMING", "LIVE"], states

    reaches_live(source)
    with pytest.raises(AssertionError):
        reaches_live(source.replace(CAPS_GATE_OLD, CAPS_GATE_NEW))


def test_revert_control_treating_the_latch_delta_reset_as_a_stall_is_caught(compiled, image):
    source = MODULE.read_text(encoding="utf-8")
    old = '        return restart("LOST", 0, 0)\n'
    assert source.count(old) == 2  # the generation/cookie latch, and the stall budget
    mutant = source.replace(old, LATCH_FALLTHROUGH, 1)

    def sequence(text):
        made = rig(compiled, image, source=text)
        _, state = live(made, 3)
        made.put_title("generation", 5)
        made.put_envelope("reserved", 5)
        made.put_title("cookie", 0xFEEDFACE)
        made.put_title("delta", 0)
        out = []
        for _ in range(2):
            state, reason = made.go(state)
            assert reason is None, reason
            out.append((state["state"], state["stalled"]))
        return out

    assert sequence(source) == [("LOST", 0), ("WARMING", 1)]
    with pytest.raises(AssertionError):
        assert sequence(mutant) == [("LOST", 0), ("WARMING", 1)]


# ------------------------------------------------- SOURCE falsifier for the premise

PUBLISH_SIGNATURE = "Slink_NDS_Publish(SlinkGen4State"


def publish_fields(text):
    """The `t->field = ...` statements of the ROM's publish function, in source order."""
    body = text.split(PUBLISH_SIGNATURE, 1)[1].split("Slink_NDS_Service", 1)[0]
    return re.findall(r"t->(\w+)\s*=", body)


def harness_publish_fields(text=None):
    """The `t->field = ...` statements of this module's own C harness, in source order."""
    body = (text if text is not None else HARNESS).split("static void publish(", 1)[1]
    return re.findall(r"t->(\w+)\s*=", body.split("static unsigned opt(", 1)[0])


def test_the_host_harness_stamps_the_title_in_the_roms_publish_order():
    # The binder's torn-read argument assumes payload-first / magic-LAST. That the ROM does
    # it is falsified by test_nds_mailbox.py:634; what this card owns is that its own
    # harness reproduces the REAL order instead of an idealised one.
    assert harness_publish_fields() == publish_fields(BEACON.read_text(encoding="utf-8"))


def test_the_publish_order_control_moving_the_magic_first_requires_red():
    text = HARNESS.replace("  t->cookie = s->cookie;\n", "")
    text = text.replace("  t->magic = s->magic;\n", "  t->magic = s->magic;\n  t->cookie = s->cookie;\n")
    assert harness_publish_fields(text) != publish_fields(BEACON.read_text(encoding="utf-8"))


def test_stable_saturates_instead_of_wrapping_and_dropping_live(compiled, image):
    made = rig(compiled, image)
    state, _ = made.go()
    state["stable"] = 0xFFFF  # a host that has been LIVE for 65535 advancing polls
    made.tick()
    state, reason = made.go(state)
    assert reason is None and state["state"] == "LIVE" and state["stable"] == 0xFFFF
