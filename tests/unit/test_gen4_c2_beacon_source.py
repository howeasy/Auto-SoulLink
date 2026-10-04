"""Static source falsifiers for the Gen 4 companion C2 beacon (patch/src/nds/gen4).

Pure text analysis: no compiler, no emulator, no ROM. Every invariant is a pure
detector over source text, so each red control mutates a copy of the real file and
re-runs the SAME detector the green test uses. A control that stays green means its
detector measures nothing.

  no file-scope object        a static .bss symbol moves 0x021E5900 and every pinned
                              overlay address; a const table also eats ARM9 bytes the
                              pinned layout has no slack for
  only abi.h + local names    an invented or renamed shared constant drifts silently
  main.c:51 / main.c:77       the wrong RegisterMainOverlay arms the service after the
                              first app can already run
  no opcode pre-route         routing by opcode is the retired C2 workaround; producer
                              isolation is per producer
  title window 0xE00..0xE40   D-C2-1 forbids an unversioned title block and anything
                              past 0xE40
  capabilities 0, bits 16..31 a bit set ahead of its card advertises what is not built
  capability composed after         assigning the beacon's constant erases every card's
  the fan-out                       bit; composing before the cards run makes every bit one
                                    visit stale, so a cleared bit outlives the visit that
                                    cleared it; accumulating into the mailbox keeps a bit,
                                    or a host's write, forever
  vblankCounter only          gSystem.frameCounter is zeroed every loop (main.c:124)
  no DTCM / OS_ARENA_ITCM     DTCM is the launcher stack; census W2 FAILs an ITCM alloc
  no 7-8 hex span literal     census W2 FAILs a literal inside the span, and this source
                              is compiled into the tree the census scans
  scanned scope              beacon.c/.h, dispatch and the C3 sound headers: the C2
                              invariants are whole-directory rules, so a file-scope
                              object or an in-span literal in sound_policy.h moves
                              0x021E5900 or fails census W2 exactly as one in beacon.c

Run:  pytest tests/unit/test_gen4_c2_beacon_source.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GEN4 = ROOT / "patch/src/nds/gen4"
COMMON = ROOT / "patch/src/nds/common"
ABI = COMMON / "abi.h"
README = GEN4 / "README.md"

C_SOURCES = ("beacon.c", "beacon.h", "dispatch.c", "dispatch.h")

# tools/gen4_mailbox_census.py:40,44 and abi.h:40
ARENA_SIZE = 0x1000
SPAN = (0x01FFEC00, 0x01FFFC00)
C_SOURCES = ("beacon.c", "beacon.h", "dispatch.c", "dispatch.h", "sound.h", "sound_policy.h")
TITLE_OFFSET = 0xE00
TITLE_SIZE = 0x40

_WIDTH = {"uint32_t": 4, "uint16_t": 2, "uint8_t": 1}
_STRUCT_RE = re.compile(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", re.S)
_FIELD_RE = re.compile(r"\b(uint\d+_t)\s+(\w+)\s*(?:\[\s*(\d+)\s*\])?\s*;")
_SLINK_RE = re.compile(r"\bSLINK_[A-Za-z0-9_]+\b")


# --------------------------------------------------------------------------- plumbing

def _sources(overrides: dict[str, str] | None = None) -> dict[str, str]:
    text = {name: (GEN4 / name).read_text(encoding="utf-8") for name in C_SOURCES}
    if overrides:
        text.update(overrides)
    return text


def _strip(text: str) -> str:
    """Drop comments, literals and preprocessor lines."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "''", text)
    kept, continuing = [], False
    for line in text.splitlines():
        if continuing:
            continuing = line.rstrip().endswith("\\")
            continue
        if line.lstrip().startswith("#"):
            continuing = line.rstrip().endswith("\\")
            continue
        kept.append(line)
    return "\n".join(kept)


def toplevel_statements(text: str) -> list[str]:
    """Declarations at brace depth 0. A function body is skipped wholesale and a
    function definition emits nothing; `typedef struct { ... } Name;` emits whole so it
    can be classified as a type."""
    out: list[str] = []
    cur: list[str] = []
    depth = paren = 0

    def emit() -> None:
        stmt = " ".join("".join(cur).split())
        if stmt:
            out.append(stmt)
        cur.clear()

    for ch in _strip(text):
        if ch == "{":
            depth += 1
            cur.append(ch)
            continue
        if ch == "}":
            depth -= 1
            if depth == 0 and "(" in "".join(cur).split("{")[0]:
                cur.clear()  # function definition: it declares nothing at file scope
            else:
                cur.append(ch)
            continue
        if depth != 0:
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == ";" and paren == 0:
            emit()
            continue
        cur.append(ch)
    emit()
    return out


# `(?!\s*\*)`: a name followed by "(*" is a function-POINTER declarator (an object), not a
# prototype; without it `static void (*p)(void *)` matched as `void (` + `*p)(void *` + `)`.
_PROTOTYPE = re.compile(
    r"^(?:extern\s+|static\s+)?[A-Za-z_][\w\s]*?\b[A-Za-z_]\w*\s*\((?!\s*\*)[^;{}]*\)$")
_TYPEDEF = re.compile(r"^(typedef|struct|union|enum)\b")


def file_scope_objects(text: str) -> list[str]:
    """File-scope declarations that are neither a type nor a function prototype.

    A file-scope variable of any kind lands in .bss or .data. The module is required to
    have none: all mutable state belongs to the service SysTask's heap data block.
    """
    return [s for s in toplevel_statements(text)
            if not (_TYPEDEF.match(s) or _PROTOTYPE.match(s))]


def slink_identifiers(text: str) -> set[str]:
    return set(_SLINK_RE.findall(text))


def span_literals(text: str) -> list[str]:
    """Literals the C1 census W2 row would flag (gen4_mailbox_census.py:83,188-197),
    with its \\b tightened so a `0x........u` suffix cannot hide one."""
    lo, hi = SPAN
    hits = []
    for m in re.finditer(r"\b0[xX]([0-9A-Fa-f]{7,8})(?![0-9A-Fa-f])", text):
        v = int(m.group(1), 16)
        bucket = None
        if lo <= v < hi:
            bucket = "in-span"
        elif 0x01000000 <= v < 0x02000000 and (lo & 0x7FFF) <= (v & 0x7FFF) < (hi & 0x7FFF or 0x8000):
            bucket = "mirror-alias"
        elif len(m.group(1)) == 8 and v < 0x8000 and (lo & 0x7FFF) <= v < (hi & 0x7FFF or 0x8000):
            bucket = "low-alias"
        if bucket:
            hits.append(f"{bucket} 0x{m.group(1)} line {text.count(chr(10), 0, m.start()) + 1}")
    return hits


def struct_fields(text: str, name: str) -> dict[str, int]:
    """Byte offsets of a flat struct declared in `text`, or {} when absent."""
    for body, tag in _STRUCT_RE.findall(text):
        if tag != name:
            continue
        offsets, at = {}, 0
        for ctype, field, count in _FIELD_RE.findall(body):
            offsets[field] = at
            at += _WIDTH[ctype] * (int(count) if count else 1)
        return offsets
    return {}


def _norm_hex(text: str) -> str:
    """Leading-zero-insensitive hex spelling, so 0x01FFEC00 and 0x1ffec00 compare."""
    return re.sub(r"0x0+", "0x", text.lower())


# --------------------------------------------------------------------------- detectors
# Each returns a list of findings; empty means clean. Shared by the green tests and the
# red controls, so a control can never "test" something no green test uses.

def det_file_scope_objects(src: dict[str, str]) -> list[str]:
    return [f"{name}: {s}" for name in src for s in file_scope_objects(src[name])]


def det_unknown_slink_names(src: dict[str, str]) -> list[str]:
    known = slink_identifiers(ABI.read_text(encoding="utf-8"))
    local = set().union(*(slink_identifiers(t) for t in src.values()))
    used = set().union(*(slink_identifiers(t) for t in src.values()))
    return sorted(used - known - local)


def det_registration_citation(src: dict[str, str]) -> list[str]:
    """Raw text on purpose: the citation IS a comment."""
    text = src["beacon.c"]
    out = []
    if "main.c:51" not in text:
        out.append("beacon.c does not cite InitSystemForTheGame (main.c:51)")
    if "main.c:77" not in text:
        out.append("beacon.c does not cite the first RegisterMainOverlay (main.c:77)")
    if "main.c:83" in text:
        out.append("beacon.c cites main.c:83, the SECOND overlay, as the site")
    return out


def det_opcode_route(src: dict[str, str]) -> list[str]:
    code = _strip(src["dispatch.c"])
    return [f"dispatch.c routes on opcode: {p}" for p in ("->opcode", "case SLINK_OP", "switch ")
            if p in code]


def det_span_literals(src: dict[str, str]) -> list[str]:
    return [f"{name}: {h}" for name in src for h in span_literals(src[name])]


def det_bad_capabilities(src: dict[str, str]) -> list[str]:
    header, code = src["beacon.h"], src["beacon.c"]
    out = []
    if not re.search(r"#define SLINK_GEN4_CAP_MASK_TITLE 0xFFFF0000u", header):
        out.append("title capability range is not bits 16..31")
    m = re.search(r"#define SLINK_GEN4_CAPABILITIES\s+(\S+)", header)
    if not m:
        out.append("no advertised capability set")
    elif m.group(1) != "0u":
        out.append(f"capabilities advertised at C2: {m.group(1)}")
    for name in ("SLINK_CAP_EXPLODE", "SLINK_CAP_RIVAL_SWAP", "SLINK_CAP_MATCH_CALL"):
        if name in code:
            out.append(f"beacon.c references {name}, a cap Gen 4 may never advertise")
    return out


def det_capability_composition(src: dict[str, str]) -> list[str]:
    """The published word is COMPOSED from the cards, AFTER the fan-out, by a single
    whole-word assignment.

    Three defects share one shape -- the erase: assigning the beacon's constant (which
    drops every card's bit), composing BEFORE the fan-out (every bit one visit stale, so
    a cleared bit outlives the visit that cleared it), and accumulating into the mailbox
    (a bit, or a host's write, survives forever). All three are invisible to a C2 build
    that has no card in it yet, so they are pinned here as well as by the host harnesses.
    """
    code, header = _strip(src["beacon.c"]), src["beacon.h"]
    out = []
    service = _function_body(code, "Slink_NDS_Service")
    if not service:
        return ["no Slink_NDS_Service body found"]
    dispatch_at = service.find("Slink_NDS_Dispatch(st, m)")
    caps_at = service.find("Slink_NDS_PublishCaps(st, m)")
    if dispatch_at < 0:
        out.append("the service does not run the producer fan-out")
    if caps_at < 0:
        out.append("the service does not stamp the word through Slink_NDS_PublishCaps")
    elif dispatch_at >= 0 and caps_at < dispatch_at:
        out.append("the capability word is stamped BEFORE the fan-out: every bit would be "
                   "one visit stale and a card's cleared bit would survive the visit")
    direct = re.findall(r"m->capabilities\s*(?:=|\|=|&=|\^=)", code)
    if direct:
        out.append(f"beacon.c writes m->capabilities directly ({len(direct)}x): the "
                   f"composition helper is the single writer, a card is not")
    helper = _function_body(_strip(header), "Slink_NDS_PublishCaps")
    if not helper:
        out.append("beacon.h has no Slink_NDS_PublishCaps body")
    else:
        if "m->capabilities = caps & SLINK_GEN4_CAP_MASK_LEGAL;" not in helper:
            out.append("the composition does not assign the masked sum of the cards' words "
                       "(an accumulate here is exactly the stale-bit defect)")
    for card in ("sound", "panel", "trade"):
        arm = (r"#if defined\(SLINK_GEN4_" + card.upper() + r"\)\s*\n"
               r"\s*caps \|= st->" + card + r"\.caps;\s*\n#endif")
        if not re.search(arm, header):
            out.append(f"the {card} contribution is not guarded by its own build flag")
        if "caps" not in struct_fields(header, "SlinkGen4State" + card.capitalize()):
            out.append(f"SlinkGen4State{card.capitalize()} has no per-card contribution word")
    return out


def det_frame_counter(src: dict[str, str]) -> list[str]:
    """Code only: the rule is also named in prose, and prose must not trip it."""
    return [f"{name}: gSystem.frameCounter" for name, t in src.items() if "frameCounter" in _strip(t)]


def det_arena_misuse(src: dict[str, str]) -> list[str]:
    """Code only, for the same reason."""
    out = []
    for name, text in src.items():
        code = _strip(text)
        if "OS_ARENA_DTCM" in code:
            out.append(f"{name}: DTCM is the launcher stack, not state")
        if "OS_ARENA_ITCM" in code:
            out.append(f"{name}: OS_ARENA_ITCM allocation fails census W2")
    if "OS_ARENA_MAIN" not in _strip(src["beacon.c"]):
        out.append("beacon.c does not allocate the state block from the MAIN arena")
    return out


def det_title_window(src: dict[str, str]) -> list[str]:
    header = src["beacon.h"]
    out = []
    if "SLINK_GEN4_TITLE_OFFSET (SLINK_RESERVED_OFFSET)" not in header:
        out.append("title window is not derived from SLINK_RESERVED_OFFSET")
    m = re.search(r"#define SLINK_GEN4_TITLE_SIZE (\S+)", header)
    size = int(m.group(1).rstrip("u"), 16) if m and m.group(1).endswith("u") else None
    if size != TITLE_SIZE:
        out.append(f"title window is {size} bytes, the ruling allows {TITLE_SIZE}")
    elif TITLE_OFFSET + size > ARENA_SIZE:
        out.append("title window overruns the arena")
    offsets = struct_fields(header, "SlinkGen4Title")
    for field, macro in (("cookie", "COOKIE"), ("identity", "IDENTITY"), ("delta", "DELTA"),
                         ("generation", "GENERATION"), ("registrations", "REGISTRATIONS")):
        declared = re.search(rf"#define SLINK_GEN4_TITLE_{macro}_FIELD (\d+)u", header)
        if not declared:
            out.append(f"no offset macro for title field {field}")
        elif offsets.get(field) != int(declared.group(1)):
            out.append(f"title field {field}: struct {offsets.get(field)} != macro {declared.group(1)}")
    if offsets.get("magic") != 0 or offsets.get("version") != 4 or offsets.get("size") != 6:
        out.append("title block is not versioned with magic/version/size in its first bytes")
    if "sizeof(SlinkGen4Title) == SLINK_GEN4_TITLE_SIZE" not in header:
        out.append("no compile-time size check on the title block")
    return out


def _function_body(code: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*\([^;{{}}]*\)\s*\{{", code)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(code) and depth:
        depth += {"{": 1, "}": -1}.get(code[i], 0)
        i += 1
    return code[m.end():i]


def det_register_latch(src: dict[str, str]) -> list[str]:
    """README items 8/9: the title block lives in the ITCM arena and survives a soft
    reset, so 'already registered in THIS boot' must never be decided by it. The latch
    has to be a per-boot structure: our own task on the (rebuilt) main queue."""
    code = _strip(src["beacon.c"])
    register = _function_body(code, "Slink_NDS_Register")
    helper = _function_body(code, "Slink_NDS_AlreadyQueued")
    if not register:
        return ["no Slink_NDS_Register body found"]
    out = []
    prelude = register.split("OS_AllocFromArenaLo")[0]
    for cond in re.findall(r"\bif\s*\(([^{}]*?)\)\s*\{\s*return\s*;", prelude):
        if re.search(r"\bt->|Slink_NDS_Title|SLINK_GEN4_TITLE_", cond):
            out.append(f"register returns early on the published title block: if ({' '.join(cond.split())})")
    if "Slink_NDS_AlreadyQueued()" not in prelude:
        out.append("register has no per-boot 'already queued' guard before it allocates")
    if "mainTaskQueue" not in helper or not re.search(r"->func\s*==\s*Slink_NDS_Service", helper):
        out.append("the latch does not look for our own service task on gSystem.mainTaskQueue")
    return out


DETECTORS = {
    "file-scope objects": det_file_scope_objects,
    "unknown SLINK_* name": det_unknown_slink_names,
    "registration site citation": det_registration_citation,
    "opcode pre-route": det_opcode_route,
    "in-span literal": det_span_literals,
    "capability set ahead of its card": det_bad_capabilities,
    "capability word composed after the fan-out": det_capability_composition,
    "frameCounter as the clock": det_frame_counter,
    "DTCM or ITCM arena": det_arena_misuse,
    "title window overruns its ruling": det_title_window,
    "register latch survives a soft reset": det_register_latch,
}


# ===================================================================== green: presence

def test_module_files_exist():
    for name in (*C_SOURCES, "README.md"):
        assert (GEN4 / name).is_file(), f"missing {name}"


# ------------------------------------------------------- scanner self-check
# toplevel_statements() is a hand-written brace scanner and the only helper here whose
# correctness is not obvious by inspection. These fixtures pin the exact shapes the
# module relies on, so a scanner regression shows up as a fixture failure rather than
# as a mystery finding against the real source.

_SCANNER_CASES = [
    ("prototype",
     "extern void SDK_SECTION_ARENA_ITCM_START(void);\n",
     []),
    ("static prototype",
     "static void Slink_NDS_Zero(volatile u8 *p, u32 n);\n",
     []),
    ("function definition declares nothing",
     "static u32 f(void)\n{\n    return 1u;\n}\n",
     []),
    ("definition with a brace inside the body",
     "static void f(void)\n{\n    if (x) {\n        y = 1;\n    }\n}\n",
     []),
    ("typedef struct is a type",
     "typedef struct {\n    u32 a;\n    u16 b;\n} Thing;\n",
     []),
    ("array typedef is a type",
     "typedef char check[(1) ? 1 : -1];\n",
     []),
    ("a variable is an object",
     "static u32 sDebugVisits;\n",
     ["static u32 sDebugVisits"]),
    # A const table is still .rodata bytes in a no-slack ARM9 image, so it is an object.
    # The scanner renders the declarator and drops the initializer body, hence the "{}".
    ("a const table is still an object",
     "static const u32 kTable[4] = {1, 2, 3, 4};\n",
     ["static const u32 kTable[4] = {}"]),
    ("a const array without an initializer is still an object",
     "static const u32 kSizes[2];\n",
     ["static const u32 kSizes[2]"]),
    ("a const function pointer is still an object",
     "static void (*const kService)(void *);\n",
     ["static void (*const kService)(void *)"]),
    ("a plain function pointer is an object too",
     "static void (*sHook)(void);\n",
     ["static void (*sHook)(void)"]),
    ("a prototype taking a function pointer is still a prototype",
     "void Register(void (*cb)(void *));\n",
     []),
    ("an extern variable is still an object",
     "extern u32 SDK_MAIN_ARENA_LO;\n",
     ["extern u32 SDK_MAIN_ARENA_LO"]),
    ("a preprocessor definition is not a declaration",
     "#define SLINK_GEN4_TITLE_SIZE 0x40u\n",
     []),
    ("a comment declaring a variable is not a declaration",
     "/* static u32 sGhost; */\nu32 f(void);\n",
     []),
    ("mixed: prototype, definition and one object",
     "void a(int x);\nstatic int b(void)\n{\n    return 0;\n}\nstatic int c;\n",
     ["static int c"]),
]


@pytest.mark.parametrize("label,source,expected", _SCANNER_CASES,
                         ids=[c[0] for c in _SCANNER_CASES])
def test_scanner_recognises_the_shapes_the_module_uses(label, source, expected):
    assert file_scope_objects(source) == expected

    # An initialized const table is the realistic "someone added a descriptor array"
    # regression; the exact rendering is pinned above, this only pins that it is caught.
    assert file_scope_objects("static const SlinkProducer kProducers[3] = {a, b, c};\n")


def test_state_block_is_the_only_mutable_home():
    src = _sources()
    assert "SlinkGen4State" in src["beacon.h"]
    assert re.search(r"OS_AllocFromArenaLo\(\s*OS_ARENA_MAIN\s*,[^;]*SlinkGen4State", src["beacon.c"])
    assert re.search(r"SysTask_CreateOnMainQueue\(\s*Slink_NDS_Service\s*,\s*st\s*,", src["beacon.c"])


def test_task_callback_uses_the_pret_signature():
    """SysTaskFunc is void (*)(SysTask *, void *) (pret include/sys_task.h:8); the
    draft's one-argument form would only work as a cast."""
    assert re.search(r"static void Slink_NDS_Service\(SysTask \*task, void \*data\)", _sources()["beacon.c"])


def test_gen4_never_pairs_with_the_gen3_abi():
    """abi.h:31-33 errors if both ABIs share a translation unit."""
    for name, text in _sources().items():
        assert "trade_targets/abi.h" not in text, name
        assert "SLINK_COMPANION_ABI_H" not in text, name
    assert '#include "abi.h"' in _sources()["beacon.h"]


def test_dispatcher_is_wired_into_every_service_visit():
    code = _sources()["beacon.c"]
    assert re.search(r"Slink_NDS_Publish\(st\);.*?Slink_NDS_Dispatch\(st, m\);", code, re.S)
    assert '#include "dispatch.h"' in code
    for name, text in _sources().items():
        if name == "dispatch.c":
            continue
        for module in ("Sound", "Panel", "Trade"):
            # the CALL form, not the declaration: a producer's own header is allowed to
            # declare Slink_NDS_<X>_Service(st, m); dispatch.c is the only caller.
            assert f"Slink_NDS_{module}_Service(st, m)" not in text, f"{name} calls a producer directly"


def test_dispatcher_carries_every_module_call_site():
    code = _sources()["dispatch.c"]
    for module in ("SOUND", "PANEL", "TRADE"):
        assert f"defined(SLINK_GEN4_{module})" in code, f"{module} has no call site"
        assert f"Slink_NDS_{module.capitalize()}_Service" in code


def test_generation_is_a_session_epoch():
    """D-C2-4: it must also move on a save-identity change, not only on a boot."""
    code = _sources()["beacon.c"]
    assert "Save_PlayerData_GetProfile" in code
    assert re.search(r"st->generation \+ 1u", code)
    assert "m->reserved = st->generation;" in code


def test_reset_latch_clears_host_owned_request_fields():
    latch = _sources()["beacon.c"].split("static void Slink_NDS_Latch")[1].split("\n}")[0]
    for field in ("m->opcode = 0;", "m->seq = 0;", "m->session_epoch = 0;",
                  "m->ack_seq = 0;", "m->status = SLINK_ST_BUSY;"):
        assert field in latch, f"reset latch omits {field}"
    assert "Slink_NDS_Zero(m->args" in latch and "Slink_NDS_Zero(m->result" in latch
    assert "Slink_NDS_Witness()" in latch, "the witness must be zeroed"


def test_status_and_ack_are_not_stamped_every_tick():
    """C3 holds BUSY across visits and producers ack through tp_ack; a per-tick stamp
    would erase both."""
    service = _sources()["beacon.c"].split("static void Slink_NDS_Service")[1].split("\n}")[0]
    assert "m->status =" not in service
    assert "m->ack_seq =" not in service


def test_title_block_is_published_last():
    """Outside the witness revision protocol the title owns its snapshot order, and the
    magic is the host's validity stamp."""
    publish = _sources()["beacon.c"].split("static void Slink_NDS_Publish")[1].split("\n}")[0]
    body = [ln.strip() for ln in publish.splitlines() if "->" in ln]
    assert body and body[-1].startswith("t->magic")


def test_readme_carries_the_integration_points():
    readme = README.read_text(encoding="utf-8")
    assert "main.c:51" in readme and "main.c:77" in readme
    assert _norm_hex(hex(SPAN[0])) in _norm_hex(readme), "the absolute span start lives in the README"
    assert _norm_hex(hex(SPAN[1])) in _norm_hex(readme), "the absolute span end lives in the README"


# ==================================================================== green: detectors

@pytest.mark.parametrize("label", sorted(DETECTORS))
def test_detector_is_clean_on_the_real_source(label):
    findings = DETECTORS[label](_sources())
    assert findings == [], f"{label}: {findings}"


# ======================================================================== red controls
# Each mutates a copy of the real source and re-runs the SAME detector the green test
# above runs.

_MUTATIONS = [
    ("beacon.c", "static void Slink_NDS_Zero(",
     "static u32 sDebugVisits;\n\nstatic void Slink_NDS_Zero(", "file-scope objects"),
    ("beacon.h", "#define SLINK_GEN4_TITLE_SIZE 0x40u",
     "#define SLINK_GEN4_TITLE_SIZE 0x200u", "title window overruns its ruling"),
    ("beacon.h", "#define SLINK_GEN4_CAPABILITIES 0u",
     "#define SLINK_GEN4_CAPABILITIES (1u << 3)", "capability set ahead of its card"),
    ("beacon.h", "#define SLINK_GEN4_CAP_MASK_TITLE 0xFFFF0000u",
     "#define SLINK_GEN4_CAP_MASK_TITLE 0xFFFFFF00u", "capability set ahead of its card"),
    ("beacon.c", "src/main.c:77", "src/main.c:83", "registration site citation"),
    # Anchor on the CODE statement: the first textual hit is the prose comment above
    # Slink_NDS_Service, which the detector deliberately strips.
    ("beacon.c", "now = gSystem.vblankCounter;", "now = gSystem.frameCounter;",
     "frameCounter as the clock"),
    ("beacon.c", "Slink_NDS_AlreadyQueued()",
     "(Slink_NDS_Title()->magic == SLINK_GEN4_TITLE_MAGIC && Slink_NDS_Title()->delta != 0)",
     "register latch survives a soft reset"),
    ("beacon.c", "SysTaskQueue *q = gSystem.mainTaskQueue;", "SysTaskQueue *q = NULL;",
     "register latch survives a soft reset"),
    ("beacon.c", "OS_AllocFromArenaLo(OS_ARENA_MAIN", "OS_AllocFromArenaLo(OS_ARENA_ITCM",
     "DTCM or ITCM arena"),
    ("beacon.c", "#define SLINK_GEN4_ARENA_DELTA 0x65E0u",
     "#define SLINK_GEN4_ARENA_DELTA 0x65E0u\n#define SLINK_GEN4_ABS_BASE 0x01FFEC00u",
     "in-span literal"),
    ("dispatch.c", "void Slink_NDS_Dispatch(",
     "void Slink_NDS_Dispatch(SlinkGen4State *st, volatile SlinkMailboxV2 *m)\n"
     "{ if (m->opcode == SLINK_OP_PLAY_SE) { return; } }\n\nvoid Slink_NDS_DispatchOld(",
     "opcode pre-route"),
    # The two detectors above are whole-directory rules, so a control must prove they now
    # reach the C3 headers too: a mutant in beacon.c alone would pass even if the scan
    # silently stopped at dispatch.
    ("sound.h", "#define SLINK_GEN4_SE_BOO 1536u",
     "#define SLINK_GEN4_SE_BOO 1536u\n\nstatic const uint16_t slink_sound_codes[4] = {1501u, 1694u, 1536u, 1500u};",
     "file-scope objects"),
    ("sound_policy.h", "static inline void slink_gen4_sound_release(",
     "static const uint32_t slink_sound_span = 0x01FFEC00u;\n\n"
     "static inline void slink_gen4_sound_release(", "in-span literal"),
    # The erase defect, in the two shapes that compile in a C2 build with no card in it.
    ("beacon.c", "    Slink_NDS_PublishCaps(st, m);",
     "    m->capabilities = SLINK_GEN4_CAPABILITIES;", "capability word composed after the fan-out"),
    ("beacon.h", "    m->capabilities = caps & SLINK_GEN4_CAP_MASK_LEGAL;",
     "    m->capabilities |= caps & SLINK_GEN4_CAP_MASK_LEGAL;", "capability word composed after the fan-out"),
    # Stamping before AND after the fan-out: the ordering this card rejected. The first
    # occurrence moves ahead of the dispatch, which is the whole defect.
    ("beacon.c", "    Slink_NDS_Dispatch(st, m);",
     "    Slink_NDS_PublishCaps(st, m);\n    Slink_NDS_Dispatch(st, m);", "capability word composed after the fan-out"),
]


@pytest.mark.parametrize(
    "target,anchor,replacement,label", _MUTATIONS, ids=[m[3] for m in _MUTATIONS])
def test_red_controls(target, anchor, replacement, label):
    original = (GEN4 / target).read_text(encoding="utf-8")
    assert anchor in original, f"red-control anchor drifted: {anchor!r}"
    detector = DETECTORS[label]
    assert detector(_sources()) == [], f"control {label!r} is already red on the real source"
    mutated = original.replace(anchor, replacement, 1)
    assert detector(_sources({target: mutated})), f"red control {label!r} did not trip"
