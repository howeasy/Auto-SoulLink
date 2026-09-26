# P3 Gen 2 client + signal binder fixes: independent review (gen2-N3, 2026-09-22)

Reviewer: gen2-N3 (non-author). Read-only on `codex/gen2-foundation` at source cut `463bc71`;
this file is the only write. Scope: `cc04bb7` (Gen 2 client on the candidate graph) and
`dfb25f6` (signal binder: boundaries, refusals as values, faint identity, evolution).
No emulator was launched. Evidence level of everything below: SOURCE/MODEL. Pins:
pokecrystal `7a7881d0`, pokegold `656583c9` (`.cache/gen2-build`), built ROMs from the same
cache. Reproductions ran under lupa (Lua 5.4 runtime of the unit suites) on the repo's own
test harnesses (`tests/unit/test_gen2_signals.py` `World`, `tests/unit/test_gen2_client.py`
`World`). The repro file is in the appendix; it was run from a scratch directory, not committed.

Counts: HIGH 2, MEDIUM 1, LOW 1, INFO 4.

## Findings (ranked)

### N3-1 HIGH, CONFIRMED (model), runtime return value PLAUSIBLE: pair registers `HL`/`DE` do not exist on BizHawk Gambatte, so evolution and whiteout can never publish, and one variant stops every signal

- Code: `lua/gen2/signals.lua:236-245` `register(name)` falls back from a single register to its
  pair (`A` -> `AF`) but never composes a pair from singles. Two callers ask for a pair:
  `signals.lua:426` `register("HL")` (evolution, added in `dfb25f6`) and the `whiteout_before_heal`
  guard `registers.DE` evaluated at `signals.lua:249-251`. `lua/gen2/run.lua:69` (added in `cc04bb7`)
  wires `register = emu.getregister`.
- Fact: BizHawk 2.11.1 Gambatte `emu.getregister` keys are `PC/SP/A..L` plus bank keys, "no
  `HL`/`AF` pairs" (repo record `docs/purergb/PLAN.md:413`, live probe). Gen 1 reads HL as
  `io.register("H") * 256 + io.register("L")` for this reason (`lua/gen1/signals.lua:50,265,274`).
- The unit fakes model the wrong key set: `tests/unit/test_gen2_signals.py:21-22` and
  `tests/unit/test_gen2_client.py:26` expose `AF/BC/DE/HL` and no single registers, so every
  suite passes through the `A -> AF` fallback and the pair keys that BizHawk lacks.
- Failure, two branches depending on what EmuHawk returns for an unknown key:
  - nil: `assert(integer(value, ...), "OPEN: CPU register unavailable")` is an invariant error,
    not a `need()` refusal. The capture wrapper (`signals.lua:568`) re-raises and the shared
    registry latches `failed`. The whiteout site sits at CPU `Special` (C `03:401b`), which every
    script `special` command runs through (`engine/events/specials.asm:1-13`). `Script_Whiteout`
    itself calls `special FadeOutToWhite` before `special HealParty`. So the first `special`
    of the session in that bank stops ALL Gen 2 signals (captures, faints, PC ops included).
  - 0: `register("DE") == 0 ~= 27` makes the whiteout guard refuse forever, and
    `register("HL") == 0` fails `need(... == wPartySpecies+slot)` so every evolution is a refusal.
    No whiteout and no evolution `key_change` ever reaches the server.
- Repro: `test_r1_*` (appendix). With the BizHawk key set: nil branch gives `status().failed`
  containing "CPU register" for both sites; 0 branch gives refusals "species-list store does not
  name wCurPartyMon" and "register guard refused". Control `test_r1_control_pair_model_passes`
  shows the shipped pair-key fake emits the whiteout.
- Fix direction: in `register()`, build a requested pair from its two halves (`H*256+L`,
  `D*256+E`) and treat a nil/absent single as a refusal. Change both unit fakes to expose exactly
  BizHawk's key set (`PC SP A B C D E F H L`), and add one falsifier per pair caller.

### N3-2 HIGH, CONFIRMED: a start latch left by a native failure or cancel path makes the next attempt of the same operation publish nothing

- Code: `signals.lua:518-523` refuses a start when `latches[name]` is still set ("duplicate
  acquisition start in one operation"), and the refusal handler (`signals.lua:561-566`) then
  retires every latch. The client's authority (`lua/gen2/client.lua:650-654`) gives one
  operation id per reset epoch (`"epoch-" .. epoch`), so nothing retires an unconsumed start
  between two native attempts. The client never calls `boundary("failure"|"cancel")`, and the
  only binder-side retirements are the reset/reload/battle_end sites (`signals.lua:55`).
- Source: the begin sites sit before a native failure branch that skips the complete site.
  - `pc_deposit_begin` is the `predef SendGetMonIntoFromBox` of `DepositPokemon`. Its
    `jr c, .BoxFull` (C `engine/pokemon/bills_pc.asm:1778-1779,1809`, G `:1756-1757,1787`) never
    reaches `pc_deposit_complete`.
  - `pc_withdraw_begin`, `jr c, .PartyFull` (C `:1833-1834,1864`, G `:1811-1812,1842`).
  - `change_box_begin` is the `ChangeBoxSaveGame` entry. Answering "No" at `YesNoBox`, or
    declining `AskOverwriteSaveFile`, jumps to `.refused` (C `engine/menus/save.asm:39-60`,
    G `:40-61`) and never reaches `change_box_loaded`.
  The engine-site doc says so itself ("deposit/withdraw failure carry branches bypass the
  post-compaction site", `docs/gen2/gen2_engine_sites.md`, Mandatory guards / PC operations).
- Failure: the player tries to deposit into a full box ("BOX is full"), changes box, and deposits
  again. The second `pc_deposit_begin` is refused as a duplicate, all latches are wiped, and
  `pc_deposit_complete` finds no prior. No `party_to_box` is sent, so the server keeps the key in
  `party_keys` and never boxes the partner's half (protocol §4 `party_to_box`). A declined box
  change followed by an accepted one loses the `box_change`, which leaves `pc_boxes` stale until
  some other event triggers a rescan. The pattern repeats: every attempt right after a failed one
  is lost.
- Repro: `test_r2_box_full_deposit_then_real_deposit_is_lost` gives no event, a refusal
  "duplicate acquisition start", and `failed` nil. `test_r2_declined_change_box_then_real_change_is_lost`
  gives the same. `test_r2_control_single_deposit_publishes` is the positive control. The existing
  `test_pc_failure_or_ambiguous_identity_cannot_publish_completion` covers only a complete site
  firing without a copy, not a failure that skips the complete site.
- Fix direction: a new start of an operation-kind start (PC deposit/withdraw/release, change box,
  NPC trade) should supersede the unconsumed prior start (retire it, count it in `drops`) instead
  of refusing. Keep the duplicate refusal for the acquisition pairs (capture/hatch/contest), where
  the source has no failure path between start and final. Alternatively register the failure
  branches (`.BoxFull`, `.PartyFull`, `ChangeBoxSaveGame.refused`) as `failure` boundaries.

### N3-3 MEDIUM, CONFIRMED (mechanism) / PLAUSIBLE (trigger): any refused capture in a resolving wild battle turns into a `no_catch`, which dead-zones an area where a mon was caught

- Code: `client.lua:461-473` sends `no_catch` at `battle_end` whenever `self.battle.captured` is
  false. Only `publish_capture` sets that flag (`client.lua:435`). Since `dfb25f6` a refused
  capture is silent to the client apart from a one-time log line (`client.lua:685-691`).
- Failure: the mon is in the party or box, but the binder refused its capture: ambiguous receiver
  identity, receiver snapshot unavailable, held identity changed, topology changed, and so on.
  The server then gets `no_catch{area_id}`. Protocol §4 says the area becomes DEAD_ZONE, the
  partner's pending capture gets `force_faint` + `memorialize`, and the caught mon is never
  linked. The damage is irreversible and there is no NACK path.
- Repro: `test_r3_refused_capture_sends_no_catch_for_a_caught_mon`. A wild battle on route_29
  catches a record identical to the lead, the binder refuses "ambiguous receiver identity", and
  the client sends `no_catch` for `route_29`. The trigger in that repro is contrived. Refusal
  reasons are, by design, rare runtime conditions; the harm is what makes this MEDIUM.
- Fix direction: when a capture-family site (`capture_*`, `contest_*`, roamer classifiers) records
  a refusal during the current battle, withhold `no_catch` for that battle, and log/HUD it for the
  operator. Do not infer a capture. The binder could expose a per-battle "acquisition refused"
  flag through `status()`, or attach the refused site to the `battle_end` observation.

### N3-4 LOW, CONFIRMED: events reach the server before the first hello on the candidate graph

- Code: `send()` (`client.lua:69-78`) checks only `net.connected()`. The hello waits for the
  checkpoint or a battle (`client.lua:581-591`). The run.lua checkpoint always refuses
  (`lua/gen2_write_safety.lua:172-174`), so in the overworld the first hello only comes with the
  first battle.
- Failure: poison faints, PC deposits/withdrawals, stone evolutions and egg hatches that happen
  before the first wild/trainer battle after connect or reset are sent to a server that has no
  hello (and no `rom_type`) for this session yet. Gen 1 has the same `send()`, but its qualified
  checkpoint makes the gap a few frames, not minutes.
- Repro: `test_r4_overworld_event_before_any_hello` shows `faint` as the first message ever sent.
- Fix direction: gate event sends on `hello_session:status().ready`, or queue them until the hello
  is sent. Otherwise record this as an accepted limitation until P3b.5 qualifies the checkpoint.

### INFO

- I1 (known-open, still present): omitting eggs from the wire party makes the server's
  `party_size` (`server/state.py:180`, set from the snapshot length) undercount while an egg is
  carried. `cc04bb7` already names this as open. `party_mon` is NACKed on Gen 2 today, so it has
  no effect yet. It matters as soon as the box executor lands.
- I2 (Gen 1 parity): `rescan_boxes` (`client.lua:183-196`) silently skips a box that fails to
  read, while the party fails closed. Gen 1 does the same (`lua/gen1/client.lua:290-311`).
  `pc_boxes` feeds the server's key-in-use preflight for `key_change` (`server/state.py:168`).
- I3 (Gen 1 parity): `key_alias` holds one alias (`client.lua:512`). Two evolutions in one
  `EvolveAfterBattle` pass overwrite the first alias. Acks usually arrive well before the next
  animation completes, so this is theoretical.
- I4: `validate()` can raise a reset boundary before `drain()` in the same frame
  (`client.lua:244,672-674`), so observations stamped with the previous epoch in that frame are
  dropped as stale. This only happens while `ot_id == 0` with an empty party (title screen, new
  game before the starter), and the dropped `continue_confirmed`/`new_game` boundary is redundant
  with the validate boundary. No consequence found.

## Checked and found correct

- Boundary delivery (`dfb25f6` item 1): `clear()` moves the service queue into `carried` before it
  retires latches (`signals.lua:203-208`). `drain()` returns `carried` then the live queue, which
  keeps engine order. A `battle_end`/reset in the same frame as a final no longer loses it (tests
  `test_a_boundary_delivers_a_capture_finalized_before_it`,
  `test_a_capture_finalized_in_the_boundary_frame_is_published`). Only `observation`/`faint`
  stamped with a superseded operation are dropped and counted. Faint HP-0 settles on the same
  frame: `UpdateFaintedPlayerMon` calls `UpdateBattleMonInParty` (C `engine/battle/core.asm:2656-2670`).
- Refusals as values (`dfb25f6` item 2): every latch mutation in `process()` happens after all
  `need()` checks (`signals.lua:516-526`), so a refusal never leaves a half-updated latch set.
  Refusals clear latches and return nil. Invariant asserts still latch the registry.
- Writes fail closed: `run_deferred` writes only after `safety.check()`, inside
  `writes:arm("overworld")` with `pcall` + unconditional `disarm()` (`client.lua:379-410`).
  `faint_active_battler` always errors inside `gate:guard` (no emission). `faint_party_slot`
  preflights both discontiguous spans before any emit (`lua/write_permit.lua:111-151`). run.lua's
  `authorize` returns false, so the candidate graph writes nothing. A refused KO is logged and
  shown, never reported as a KO.
- Identity (`dfb25f6` item 3): faint keys come from the party struct at the engine's own index
  (`wCurBattleMon`, or `wCurPartyMon` via `GetPartyParamLocation`, C `engine/events/poisonstep.asm:59-86`).
  The party struct is not changed by Transform, so the key is final. Capture requires
  `mon_key(m) == m.key`. Eggs never reach party/box entries, and slots stay explicit (wire refuses
  eggs as a second barrier). Hatch is published as `gift_daycare` with `gift=true`.
- Evolution (`dfb25f6` item 4): the hook is the `push hl` after `ld [hl], a` in `.skip_unown`
  (C `engine/pokemon/evolve.asm:312-317`). A = `wTempMonSpecies` and HL = the `wPartySpecies`
  walk pointer, both correct. B-cancel `jp c, CancelEvolution` skips the store. The link-trade call
  is refused via `wLinkMode`. I parsed `data/pokemon/evos_attacks.asm` in both repos independently:
  122 new-species entries per title, no species with more than one pre-evolution, and 0
  differences against `identity_migration.old_species_by_new` in all three packs. The
  `wEvolutionOldSpecies`/`wListMovesLineSpacing` aliasing rationale holds. (The register-name
  defect in N3-1 is separate.)
- NPC trade: `npc_trade_begin` is after acceptance and species/gender checks, and there is no
  failure path to `.incomplete` (C `engine/events/npc_trade.asm:1-50,114-196`). Capture start and
  final both sit inside `PokeBallEffect`, before `ExitBattle`, and the box path cannot fail after
  `SendMonIntoBox` (C `engine/items/item_effects.asm`, `.not_celebi` onward). Battle-type numbers
  (0/4/5/6/8) match both enums.
- Shared modules / Gen 1 (item 5): `git diff --stat cc04bb7^ dfb25f6` touches no shared `lua/*.lua`,
  no `lua/gen1/*` and no `server/*`. The shared modules contain no gen1/gen2/game_id branch. The
  client injects its policy into `hello_session` (`clock_rewind="keep"`, `callback_error="raise"`,
  retry 1) and into `reply_dispatch` (`budget=math.huge`), the same values Gen 1 uses.
- Hello/composition (item 6): `ready` requires a live game and either `battle.mode ~= 0` or
  `safety.check()`, and re-checks identity. `send_now` (skips ready) is harness-only, as in Gen 1.
  `Entry.build` still refuses ("production runtime composition is not implemented"). The client
  exists only on `Entry.build_candidate` (model_only IO, `signals.new_model`, injected checkpoint),
  which run.lua uses and says so in its log line.

## Commands run

- `python -m pytest tests/unit/test_gen2_client.py tests/unit/test_gen2_signals.py tests/unit/test_gen2_entry.py tests/unit/test_gen2_wire.py tests/unit/test_gen2_writes.py -q -p no:cacheprovider`: 201 passed.
- `python -m pytest tests/unit/test_gb_hook_binding.py tests/unit/test_gen1_client.py tests/unit/test_hello_session.py tests/unit/test_hook_registry.py tests/unit/test_reply_dispatch.py tests/unit/test_write_permit.py -q -p no:cacheprovider`: 272 passed.
- Scratch `test_n3_repro.py` (appendix): 10 passed. Every assertion encodes the defective
  behaviour, so each pass is the defect reproducing. The three controls pass on the shipped code.
- Scratch `evo_check.py`: independent `evos_attacks.asm` parse, 122/122 equal in crystal/gold/silver.

## Appendix: reproduction file (scratch, run from outside the repo)

```python
"""N3 reviewer reproductions (scratch, not committed). MODEL only."""
import sys
from pathlib import Path

ROOT = Path(r"E:/Google Drive/SLink/.claude/worktrees/gen2-foundation")
sys.path.insert(0, str(ROOT / "tests/unit"))
sys.path.insert(0, str(ROOT))
import test_gen2_signals as S  # noqa: E402
import test_gen2_client as C  # noqa: E402

BIZHAWK_KEYS = ("PC", "SP", "A", "B", "C", "D", "E", "F", "H", "L")  # docs/purergb/PLAN.md:413


class ZeroDict(dict):
    def get(self, k, d=None):
        return dict.get(self, k, 0)


def bizhawk_regs(world, zero_for_unknown):
    regs = (ZeroDict if zero_for_unknown else dict)({k: 0 for k in BIZHAWK_KEYS})
    regs["SP"] = world.reg["SP"]
    world.reg = regs
    return regs


def r1_evolution(zero):
    world = S.World()
    binder = world.bind()
    regs = bizhawk_regs(world, zero)
    world.party([world.mon(species=26)])
    world.field("wCurPartyMon", 0)
    world.field("wLinkMode", 0)
    hl = world.p["ram"]["wPartySpecies"]
    regs["A"], regs["H"], regs["L"] = 26, hl >> 8, hl & 255
    world.fire("evolution_species_published")
    events = world.events(binder)
    st = binder.status(binder)
    return [e.kind for e in events], st.failed, dict(st.refusals.items()) if st.refusals else {}


def r1_whiteout(zero):
    world = S.World()
    binder = world.bind()
    regs = bizhawk_regs(world, zero)
    world.party([world.mon(hp=0)])
    de = world.sites["whiteout_before_heal"]["guards"]["registers"]["DE"]
    regs["D"], regs["E"] = de >> 8, de & 255
    g = world.sites["whiteout_before_heal"]["guards"]
    for field in g.get("memory_equals", []):
        world.field(field["symbol"], field["value"], field["width"])
    for field in g.get("stack_words_equals", []):
        a = world.reg["SP"] + field["sp_offset"]
        world.memory["System Bus", a] = field["value"] & 255
        world.memory["System Bus", a + 1] = field["value"] >> 8
    world.fire("whiteout_before_heal")
    events = world.events(binder)
    st = binder.status(binder)
    return [e.kind for e in events], st.failed, dict(st.refusals.items()) if st.refusals else {}


def test_r1_evolution_nil_register_stops_registry():
    kinds, failed, _ = r1_evolution(zero=False)
    assert kinds == [] and failed and "CPU register" in failed


def test_r1_evolution_zero_register_refused_forever():
    kinds, failed, refusals = r1_evolution(zero=True)
    assert kinds == [] and failed is None
    assert "species-list store" in refusals["evolution_species_published"]


def test_r1_whiteout_nil_register_stops_registry():
    kinds, failed, _ = r1_whiteout(zero=False)
    assert kinds == [] and failed and "CPU register" in failed


def test_r1_whiteout_zero_register_never_fires():
    kinds, failed, refusals = r1_whiteout(zero=True)
    assert kinds == [] and failed is None and "register guard" in refusals["whiteout_before_heal"]


def test_r1_control_pair_model_passes():
    world = S.World()
    binder = world.bind()
    world.party([world.mon(hp=0)])
    world.set_guards("whiteout_before_heal")
    world.fire("whiteout_before_heal")
    assert [e.kind for e in world.events(binder)] == ["whiteout"]


def test_r2_box_full_deposit_then_real_deposit_is_lost():
    world = S.World()
    binder = world.bind()
    a, b = world.mon(species=25), world.mon(species=172, dvs=0x3AAA)
    world.party([a, b])
    world.box([])
    world.field("wCurPartyMon", 0)
    world.fire("pc_deposit_begin")          # SendGetMonIntoFromBox -> carry -> .BoxFull
    assert world.events(binder) == []
    world.fire("pc_deposit_begin")          # the next attempt
    world.party([b])
    world.box([a])
    world.fire("pc_deposit_complete")
    events = world.events(binder)
    st = binder.status(binder)
    assert [e.kind for e in events] == []   # party_to_box lost
    assert "duplicate acquisition start" in st.refusals.pc_deposit_begin
    assert st.failed is None


def test_r2_control_single_deposit_publishes():
    world = S.World()
    binder = world.bind()
    a, b = world.mon(species=25), world.mon(species=172, dvs=0x3AAA)
    world.party([a, b])
    world.field("wCurPartyMon", 0)
    world.fire("pc_deposit_begin")
    world.party([b])
    world.box([a])
    world.fire("pc_deposit_complete")
    assert [e.kind for e in world.events(binder)] == ["party_to_box"]


def test_r2_declined_change_box_then_real_change_is_lost():
    world = S.World()
    binder = world.bind()
    world.reg["DE"] = 2
    world.fire("change_box_begin")          # YesNoBox "No" -> .refused
    world.events(binder)
    world.fire("change_box_begin")
    world.field("wCurBox", 2)
    world.box([world.mon(species=133)])
    world.fire("change_box_loaded")
    assert [e.kind for e in world.events(binder)] == []
    assert "duplicate acquisition start" in binder.status(binder).refusals.change_box_begin


def test_r3_refused_capture_sends_no_catch_for_a_caught_mon():
    world = C.World()
    world.hello()
    world.reply({"cmd": "resolved_areas", "areas": []})
    world.frames(1)
    world.field("wBattleMode", 1)
    world.fire("wild_ready")
    caught = C.mon()                          # same DV/OT/species as the lead: receiver refuses
    world.party([C.mon(), caught])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.frames(1)
    world.fire("battle_end")
    world.field("wBattleMode", 0)
    world.frames(1)
    assert world.sent("capture") == []
    assert [n["area_id"] for n in world.sent("no_catch")] == ["route_29"]


def test_r4_overworld_event_before_any_hello():
    world = C.World()
    world.party([C.mon(hp=0), C.mon(species=172, dvs=0x3AAA)])
    world.frames(120)
    assert world.sent("hello") == []
    world.field("wCurPartyMon", 0)
    world.fire("poison_faint")
    world.frames(1)
    assert [m["event"] for m in world.sent()] == ["faint"]
```
