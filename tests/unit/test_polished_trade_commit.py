"""C5 assembled-byte MODEL: real removal/rotation/temp-copy/append/checksum paths.
Native animation, evolution, map UI, save and SRAM-open/close are traps. SRAM
bank routing is an explicit fixture hook; no interrupts/timing or durability proof.
The release remains commit-disabled; direct helper calls use an authenticated
private APPLY context, realistic C0xx SP, and exact staged/snapshot images.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit import polished_sm83 as S
from tests.unit.test_polished_trade_service import (
    APPLY,
    HROMBANK,
    MAGIC,
    TOKEN,
    Env,
    P,
    incoming_record,
    name,
    own_record,
)
from tools.build_gen2_companion import _symbols
from tools.build_polished_companion import ups_apply

ROOT = Path(__file__).resolve().parents[2]
RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
SP = 0xC0C0  # room for caller bridge/service context above, native calls below
CONTROLS = ("wLinkMode", "wForceEvolution", "wCurPartyMon", "wPokemonWithdrawDepositParameter",
            "wCurTradePartyMon", "wCurOTTradePartyMon", "wJumptableIndex", "wTradeDialog",
            "wStateFlags", "wSpriteUpdatesEnabled", "hVBlank", "rSVBK")


@pytest.fixture(scope="module")
def env():
    if not RELEASE.is_file():
        pytest.skip(f"release ROM missing: {RELEASE}")
    e = Env(ups_apply(RELEASE.read_bytes(), (ROOT / "patch/dist/SLink-Polished.ups").read_bytes()),
            _symbols(ROOT / "data/polished/polished_slink.sym"),
            _symbols(ROOT / "data/polished/polishedcrystal.sym"))
    assert e.sym["SlinkTradeCommit"] == (0x7E, 0x5300), "present old artifact is not C5"
    return e


class Rig:
    def __init__(self, env, count=4, slot=1, role=0, record=None, fault=None):
        self.e, self.count, self.slot, self.role, self.fault = env, count, slot, role, fault
        self.m = S.SM83(env.rom, 0x7E, mbc="mbc3", farcall="model", hrombank=HROMBANK)
        self.events, self.sram_writes = [], []
        self.phase = "preflight"
        self.sbank = 0
        self.sram = {b: bytearray(0x2000) for b in range(16)}
        self.staged = bytes(incoming_record() if record is None else record)
        self.incoming_ot = name(60)[:8] + b"\x91\x2A\xC7"
        m, a = self.m, self.a
        m.poke(HROMBANK, 0x7E)
        for n in CONTROLS:
            m.poke(a(n), 0)
        m.poke(a("rSVBK"), 1)
        for n in ("wCurPartyMon", "wCurTradePartyMon", "wCurOTTradePartyMon", "wJumptableIndex", "wTradeDialog"):
            m.poke(a(n), 0xA4)
        m.poke(a("wPartyCount"), count)
        m.poke(a("wSavedAtLeastOnce"), 1)
        m.poke(a("wPlayerName"), name(40))
        for i in range(6):
            r = bytearray(own_record(i))
            r[34:38] = b"\x00\x14\x00\x28"
            m.poke(a("wPartyMon1") + i * P, r)
            m.poke(a("wPartyMonOTs") + i * 11, name(40 + i)[:8] + bytes((i + 1, i + 20, i + 70)))
            m.poke(a("wPartyMonNicknames") + i * 11, name(50 + i))
        m.poke(a("wOTPartyMon1"), self.staged)
        m.poke(a("wOTPartyMonOTs"), self.incoming_ot)
        m.poke(a("wOTPartyMonNicknames"), name(70))
        m.poke(a("wOTPlayerName"), name(80))
        self.original = self.party()
        for dst, src, n in ((a("wOTPartyMon2"), a("wPartyMon1") + slot * P, P),
                            (a("wOTPartyMonOTs") + 11, a("wPartyMonOTs") + slot * 11, 11),
                            (a("wOTPartyMonNicknames") + 11, a("wPartyMonNicknames") + slot * 11, 11)):
            m.poke(dst, m.peek(src, n))
        lease = bytes((*MAGIC, 1, APPLY, 0x12, 0x12, 0, slot, 1, 0x3F, *TOKEN))
        m.poke(env.lease, lease)
        m.poke(SP, bytes((*TOKEN, slot, role, 0x12, 0, count, 0)))
        self.before_controls = {n: m.peek(a(n)) for n in CONTROLS}
        mail_bank, mail_addr = env.sym["sPartyMon1Mail"]
        self.mail_len = env.sym["sPartyMon2Mail"][1] - mail_addr
        self.mail_bank, self.mail_addr = mail_bank, mail_addr
        for i in range(6):
            self.sram[mail_bank][mail_addr - 0xA000 + i * self.mail_len:mail_addr - 0xA000 + (i + 1) * self.mail_len] = bytes([i + 1]) * self.mail_len
        self.before_mail = self.mail()
        for addr in range(0xA000, 0xC000):
            m.mem.read_hooks[addr] = lambda mem, p: self.sram[self.sbank][p - 0xA000]
            m.mem.write_hooks[addr] = self.write_sram
        self.trap("GetSRAMBank", self.open_sram)
        self.trap("CloseSRAM", lambda mm: None)
        self.trap("CompareLoadedAndSavedPlayerID", lambda mm: setattr(mm, "zf", self.fault != "identity"))
        for n in ("DisableSpriteUpdates", "ClearTileMap", "LoadFontsBattleExtra", "GetCGBLayout", "RestartMapMusic", "ReturnToMapWithSpeechTextbox"):
            self.trap(n, lambda mm, n=n: self.events.append(n))
        for n in ("TradeAnimation", "TradeAnimationPlayer2"):
            self.trap(n, lambda mm, n=n: self.animation(n))
        self.trap("EvolvePokemon", self.evolve)
        self.trap("ForceGameSave", self.save)
        self.executed = set()
        orig_step = m.step
        def step():
            self.executed.add((m.bank if m.pc >= 0x4000 else 0, m.pc))
            if m.pc == env.a("SlinkTradeCommit.Mutation") and m.bank == 0x7E:
                self.phase = "commit"
            w0 = len(m.mem.writes)
            orig_step()
            if self.phase == "preflight":
                early = [(0xC000, SP), (self.a("wPlayerTrademonSpecies"), self.a("wPlayerTrademonSpecies") + 106)]
                early.extend((self.a(n), self.a(n) + 1) for n in (*CONTROLS, "hROMBank"))
                for pc, p, value in m.mem.writes[w0:]:
                    assert any(lo <= p < hi for lo, hi in early), f"preflight wrote {pc:04x}:{p:04x}={value:02x}"
        m.step = step

    def a(self, n):
        if n == "rSVBK":
            return 0xFF70  # hardware register, not a linker label
        return self.e.a(n)

    def trap(self, n, fn):
        bank, addr = self.e.sym[n]
        self.m.trap(addr, fn, bank=bank if bank else None)

    def write_sram(self, mem, addr, value):
        assert self.phase in ("commit", "save"), "SRAM before mutation"
        if self.phase == "commit":
            assert self.sbank == self.mail_bank and self.mail_addr <= addr < self.mail_addr + 6 * self.mail_len
        else:
            spans = [(self.e.sym[n][0], self.a(n), self.a(end) - self.a(n))
                     for n, end in (("sGameData", "sGameDataEnd"), ("sBackupGameData", "sBackupGameDataEnd"))]
            assert any(b == self.sbank and lo <= addr < lo + size for b, lo, size in spans) or addr in (self.a("sChecksum"), self.a("sChecksum") + 1, self.a("sBackupChecksum"), self.a("sBackupChecksum") + 1, self.a("sWritingBackup"))
        self.sram[self.sbank][addr - 0xA000] = value
        self.sram_writes.append((self.phase, self.sbank, addr, value))
        return False

    def open_sram(self, m):
        self.sbank = m.a
        assert self.sbank in self.sram

    def party(self):
        return [self.m.peek(self.a("wPartyMon1") + i * P, P) + self.m.peek(self.a("wPartyMonOTs") + i * 11, 11) + self.m.peek(self.a("wPartyMonNicknames") + i * 11, 11) for i in range(self.count)]

    def mail(self):
        lo = self.mail_addr - 0xA000
        return bytes(self.sram[self.mail_bank][lo:lo + 6 * self.mail_len])

    def animation(self, n):
        self.events.append(n)
        assert self.m.peek(self.a("wPartyCount"))[0] == self.count - 1
        # Display must include the third DV and full personality/form, even for extended eggs.
        for prefix, source in (("wPlayerTrademon", self.original[self.slot][:P]), ("wOTTrademon", self.staged)):
            assert self.m.peek(self.a(prefix + "DVs"), 3) == source[17:20]
            assert self.m.peek(self.a(prefix + "Personality"))[0] == source[20]
            form = source[21] & ~0x20 if source[21] & 0x40 else source[21]
            assert self.m.peek(self.a(prefix + "Form"))[0] == form
            assert self.m.peek(self.a(prefix + "Species"))[0] == (0xFF if source[21] & 0x40 else source[0])
        if self.fault == "animation-staging":
            self.m.poke(self.a("wOTPartyMon1Level"), 0)

    def evolve(self, m):
        self.events.append("EvolvePokemon")
        assert m.peek(self.a("wForceEvolution"))[0] == 3
        assert m.peek(self.a("wLinkMode"))[0] != 0
        assert m.peek(self.a("wCurPartyMon"))[0] == self.count - 1
        if self.fault == "evolution-count":
            m.poke(self.a("wPartyCount"), self.count - 1)
        if self.fault == "evolution-identity":
            p = self.a("wPartyMon1DVs") + (self.count - 1) * P
            m.poke(p, m.peek(p)[0] ^ 1)

    def save(self, m):
        self.events.append("ForceGameSave")
        self.phase = "save"
        m.cf = self.fault == "save-carry"
        if m.cf:
            return
        if self.fault == "save-missing":
            return
        size = self.a("wPokemonDataEnd") - self.a("wPokemonData")
        post = m.peek(self.a("wPokemonData"), size)
        for span, end, data, check in (("sGameData", "sGameDataEnd", "sPokemonData", "sChecksum"),
                                      ("sBackupGameData", "sBackupGameDataEnd", "sBackupPokemonData", "sBackupChecksum")):
            self.sbank = self.e.sym[span][0]
            for i, value in enumerate(post):
                m.wr(self.a(data) + i, value)
            if self.fault == "save-postimage" and data == "sBackupPokemonData":
                m.wr(self.a(data), post[0] ^ 1)
            bank = self.sram[self.sbank]
            checksum = sum(bank[self.a(span) - 0xA000:self.a(end) - 0xA000]) & 0xFFFF
            if self.fault == "save-checksum" and data == "sPokemonData":
                checksum ^= 1
            m.wr(self.a(check), checksum & 255)
            m.wr(self.a(check) + 1, checksum >> 8)
        self.sbank = self.e.sym["sWritingBackup"][0]
        m.wr(self.a("sWritingBackup"), int(self.fault == "save-phase"))

    def run(self):
        return self.m.call_routine(self.a("SlinkTradeCommit"), {"a": self.slot, "b": self.role, "c": 0x71, "de": 0x1234, "hl": 0x2345}, sp=SP, bank=0x7E, max_steps=500_000)

    def invariant(self, result):
        assert result.sp_delta == 0 and result.min_sp >= 0xC000
        assert result.bc == (self.role << 8 | 0x71) and result.de == 0x1234 and result.hl == 0x2345
        assert self.m.bank == 0x7E and self.m.peek(HROMBANK)[0] == 0x7E
        assert {n: self.m.peek(self.a(n)) for n in CONTROLS} == self.before_controls
        # Exact allowed CPU destinations (native traps write through poke separately).
        spans = [(0xC000, SP), (self.e.lease, self.e.lease + 16)]
        for n, size in (("wPartyCount", 1), ("wPartyMon1", 6 * P), ("wPartyMonOTs", 66),
                        ("wSwitchMonBuffer", 48),
                        ("wPartyMonNicknames", 66), ("wTempMon", 48), ("wTempMonOT", 11), ("wTempMonNickname", 11),
                        ("wPlayerTrademonSpecies", 106), ("wPokedexCaught", 0x32), ("wPokedexSeen", 0x32),
                        ("wNamedObjectIndex", 2), ("wCurPartySpecies", 1), ("wCurForm", 1), ("wDexCacheValid", 1)):
            spans.append((self.a(n), self.a(n) + size))
        spans.extend((self.a(n), self.a(n) + 1) for n in (*CONTROLS, "hROMBank"))
        for pc, addr, value in result.writes:
            if 0xA000 <= addr < 0xC000:
                continue  # bank-qualified phase whitelist checked at each write
            assert any(lo <= addr < hi for lo, hi in spans), f"forbidden CPU write {pc:04x} {addr:04x}={value:02x}"


@pytest.mark.parametrize("count,slot", [(1, 0), (6, 0), (6, 2), (6, 5), (4, 1)])
@pytest.mark.parametrize("role", [0, 1])
def test_native_exchange_count_order_names_mail_and_full_save(env, count, slot, role):
    r = Rig(env, count, slot, role)
    result = r.run()
    assert result.a == 0
    r.invariant(result)
    expected = [p for i, p in enumerate(r.original) if i != slot]
    inc = bytearray(r.staged)
    inc[26] = 70  # BASE_HAPPINESS; native append alone is permitted to change it
    expected.append(bytes(inc) + r.incoming_ot + name(70))
    assert r.party() == expected
    mail = [r.before_mail[i * r.mail_len:(i + 1) * r.mail_len] for i in range(6)]
    mail[slot:count] = mail[slot + 1:count] + mail[slot:slot + 1]
    assert r.mail() == b"".join(mail)
    assert bool([w for w in r.sram_writes if w[0] == "commit"]) == (slot != count - 1)
    for n in ("RemoveMonFromParty", "ShiftPartySlotToEnd", "CopyBetweenPartyAndTemp", "AddTempMonToParty"):
        assert r.e.sym[n] in r.executed, n
    assert r.events == ["DisableSpriteUpdates", "ClearTileMap", "LoadFontsBattleExtra", "GetCGBLayout",
                        "TradeAnimation" if role == 0 else "TradeAnimationPlayer2", "EvolvePokemon",
                        "RestartMapMusic", "ReturnToMapWithSpeechTextbox", "ForceGameSave"]


@pytest.mark.parametrize("guard", ["role", "svbk", "vblank", "battle", "link", "paused", "contest", "saved", "count", "token", "slot", "generation", "command", "mail", "incoming", "own-name", "identity", "last-alive"])
def test_preflight_refusal_never_mutates_party_mail_or_save(env, guard):
    r = Rig(env, count=1, slot=0, fault="identity" if guard == "identity" else None)
    m, a = r.m, r.a
    edits = {"svbk": (a("rSVBK"), 2), "vblank": (a("hVBlank"), 1), "battle": (a("wBattleMode"), 1),
             "link": (a("wLinkMode"), 1), "paused": (a("wGameLogicPaused"), 1), "contest": (a("wStatusFlags2"), 4),
             "saved": (a("wSavedAtLeastOnce"), 0), "count": (SP + 8, 2), "token": (SP, 0), "slot": (SP + 4, 1),
             "generation": (SP + 6, 0x13), "command": (r.e.lease + 5, 3), "mail": (a("wPartyMon1Item"), 0xF5),
             "incoming": (a("wOTPartyMon1Level"), 0), "own-name": (a("wPartyMonNicknames"), bytes([0x5F]) * 11)}
    if guard in edits:
        m.poke(*edits[guard])
    elif guard == "role":
        r.role = 2
    elif guard == "last-alive":
        m.poke(a("wOTPartyMon1HP"), b"\0\0")
    before, mail = r.party(), r.mail()
    result = r.run()
    assert result.a == 1, guard
    assert r.party() == before and r.mail() == mail and not r.sram_writes
    assert not r.events
    assert result.sp_delta == 0


@pytest.mark.parametrize("byte", range(70))
def test_every_frozen_snapshot_byte_refuses_before_mutation(env, byte):
    r = Rig(env)
    if byte < 48:
        p = r.a("wOTPartyMon2") + byte
    elif byte < 59:
        p = r.a("wOTPartyMonOTs") + 11 + byte - 48
    else:
        p = r.a("wOTPartyMonNicknames") + 11 + byte - 59
    r.m.poke(p, r.m.peek(p)[0] ^ 1)
    result = r.run()
    assert result.a == 1 and r.party() == r.original and not r.sram_writes


@pytest.mark.parametrize("fault", ["animation-staging", "evolution-count", "evolution-identity", "save-carry", "save-missing", "save-postimage", "save-checksum", "save-phase"])
def test_postmutation_failure_is_uncertain_not_safe_refusal(env, fault):
    r = Rig(env, fault=fault)
    result = r.run()
    assert result.a == 2
    r.invariant(result)
    if fault.startswith("animation") or fault.startswith("evolution"):
        assert "ForceGameSave" not in r.events


@pytest.mark.parametrize("form", [1, 0x21, 0x61])
def test_extended_form_and_egg_display_preserve_underlying_identity(env, form):
    p = bytearray(incoming_record())
    p[0], p[21], p[17:20] = 1, form, b"\x31\x62\xA9"
    r = Rig(env, record=p)
    result = r.run()
    assert result.a == 0
    r.invariant(result)
    final = r.party()[-1][:P]
    assert final[0] == 1 and final[21] == form and final[17:21] == p[17:21]
    assert ("EvolvePokemon" not in r.events) == bool(form & 0x40)
    if form & 0x40:
        assert final == p


@pytest.mark.parametrize("name", ["SlinkTradeCommit.Preflight", "SlinkTradeValidateIncomingStaged", "SlinkTradeValidateSnapshot", "SlinkTradeCommit.CheckAppend", "SlinkTradeCommit.CheckIdentity", "SlinkTradeCommit.CheckSave"])
def test_dropped_guard_mutants_are_detected(env, name):
    cases = {"SlinkTradeCommit.Preflight": "identity", "SlinkTradeValidateIncomingStaged": "incoming",
             "SlinkTradeValidateSnapshot": "snapshot", "SlinkTradeCommit.CheckAppend": "append",
             "SlinkTradeCommit.CheckIdentity": "evolution-identity", "SlinkTradeCommit.CheckSave": "save-phase"}
    fault = cases[name]
    r = Rig(env, fault=fault)
    if fault == "incoming":
        r.m.poke(r.a("wOTPartyMon1Level"), 0)
    elif fault == "snapshot":
        r.m.poke(r.a("wOTPartyMon2"), r.m.peek(r.a("wOTPartyMon2"))[0] ^ 1)
    elif fault == "append":
        p = r.a("wPartyMon1") + (r.count - 1) * P + 27
        def corrupt_append(mem, addr, value):
            mem.ram[addr] = value ^ 1
            return False
        r.m.mem.write_hooks[p] = corrupt_append
    r.m.mem.poke_rom(r.a(name), b"\xAF\xC9", bank=0x7E)  # xor a / ret = discarded guard
    with pytest.raises((AssertionError, S.Fault)):
        result = r.run()
        assert result.a == (1 if fault in ("identity", "incoming", "snapshot") else 2)
        r.invariant(result)


def test_each_preflight_branch_polarity_mutant_is_detected(env):
    """Invert each actual refusal branch separately; the valid exchange must fail."""
    lo, hi, bad = (env.a("SlinkTradeCommit." + n) for n in ("Preflight", "Good", "Bad"))
    mutations = []
    for p in range(lo, hi):
        op = env.rom[env.flat("SlinkTradeCommit") + p - env.a("SlinkTradeCommit")]
        if op in (0xC2, 0xCA, 0xD2, 0xDA):
            off = env.flat("SlinkTradeCommit") + p - env.a("SlinkTradeCommit")
            if env.rom[off + 1:off + 3] == bad.to_bytes(2, "little"):
                mutations.append((p, op ^ 8))
    for p, op in mutations:
        r = Rig(env, count=1, slot=0)
        r.m.mem.poke_rom(p, bytes([op]), bank=0x7E)
        assert r.run().a == 1, f"preflight branch at {p:04x} accepted after polarity inversion"


class StopHold(Exception):
    pass


@pytest.mark.parametrize("role", [0, 1])
@pytest.mark.parametrize("status", [0, 1, 2, 0xFF])
def test_apply_result_lifecycle_no_escape_after_commit(env, role, status):
    r = Rig(env, role=role)
    m, a = r.m, r.a
    # A tail-entry shim allocates the service's real ten-byte context; there
    # is no additional return frame across PublishDone/shared waits.
    wrapper = 0x7000
    m.mem.poke_rom(wrapper, b"\xE8\xF6\xC3" + a("SlinkTradeApplyCommit").to_bytes(2, "little"), bank=0x7E)
    m.poke(SP - 12, bytes((*TOKEN, r.slot, role, 0x12, 0, r.count, 0)))
    commits, frames = [], []
    def commit(mm):
        commits.append((mm.a, mm.b))
        r.phase = "commit"  # lifecycle test traps the native boundary, not its branch decisions
        mm.a = status
    r.trap("SlinkTradeCommit", commit)
    r.trap("CloseText", lambda mm: None)
    r.trap("JoyTextDelay", lambda mm: mm.poke(a("hJoyPressed"), 2))
    def delay(mm):
        frames.append(mm.sp)
        mm.poke(a("hJoyPressed"), 2)  # B must not escape a committed hold
        mm.poke(env.lease + 5, 8)     # RELEASE with wrong slot/token first
        mm.poke(env.lease + 9, r.slot ^ 1)
        if len(frames) >= 3:
            mm.poke(env.lease + 9, r.slot)
        if len(frames) > 3601:
            raise StopHold
    r.trap("DelayFrame", delay)
    if status in (2, 0xFF):
        with pytest.raises(StopHold):
            m.call_routine(wrapper, sp=SP, bank=0x7E, max_steps=300_000)
        assert m.peek(env.lease + 8)[0] == 2 and len(frames) == 3602
    else:
        result = m.call_routine(wrapper, sp=SP, bank=0x7E, max_steps=300_000)
        assert result.sp_delta == 0
        assert len(frames) == (3 if status == 0 else 1)
        assert m.peek(env.lease + 5)[0] == 0
    assert commits == [(r.slot, role)], "a held generation called commit more than once"


@pytest.mark.parametrize("species,item,force,evolved,remaining", [
    (64, 0, 3, 65, 0),       # Kadabra's Linking Cord row needs EVOLVE_TRADE
    (64, 0x77, 3, None, 0x77),  # Everstone blocks it
    (95, 0x81, 3, 208, 0),   # Onix consumes Metal Coat
    (95, 0, 3, None, 0),
    (64, 0, 1, None, 0),     # TRUE is not EVOLVE_TRADE in Polished
])
def test_native_trade_evolution_decision_not_a_python_replacement(env, species, item, force, evolved, remaining):
    bank, addr = env.sym["CheckHowToEvolve"]
    m = S.SM83(env.rom, bank, mbc="mbc3", farcall="model", hrombank=HROMBANK)
    p = bytearray(own_record(0))
    p[0], p[1] = species, item
    for n, v in (("wPartyMon1", p), ("wPartyMonNicknames", name(20)), ("wPartyMonOTs", name(10)),
                 ("wPartyCount", 1), ("wCurPartyMon", 0), ("wEvolutionOldSpecies", species),
                 ("wEvolutionOldForm", 0), ("wLinkMode", 1), ("wForceEvolution", force), ("hROMBank", bank)):
        m.poke(env.a(n), v)
    result = m.call_routine(addr, sp=SP, bank=bank)
    assert result.zf == (evolved is None)
    if evolved is not None:
        assert m.peek(env.a("wEvolutionNewSpecies"))[0] == evolved
    assert m.peek(env.a("wTempMonItem"))[0] == remaining
    assert result.sp_delta == 0 and result.min_sp >= 0xC000


def test_unselected_local_mail_is_refused(env):
    r = Rig(env, count=4, slot=2)
    r.m.poke(r.a("wPartyMon1Item"), 0xF5)
    before = r.party()
    result = r.run()
    assert result.a == 1 and r.party() == before and not r.sram_writes


@pytest.mark.parametrize("count,slot", [(0, 0), (7, 0), (4, 4), (6, 6)])
def test_bad_count_or_nonexistent_outgoing_slot_is_not_performed(env, count, slot):
    r = Rig(env, count=count, slot=slot)
    before = r.party()
    result = r.run()
    assert result.a == 1 and r.party() == before and not r.sram_writes


@pytest.mark.parametrize("native", ["RemoveMonFromParty", "AddTempMonToParty"])
def test_failed_native_count_transition_is_held_without_saving(env, native):
    r = Rig(env)
    r.trap(native, lambda m: setattr(m, "cf", False))  # dropped native operation
    result = r.run()
    assert result.a == 2 and "ForceGameSave" not in r.events
    r.invariant(result)
