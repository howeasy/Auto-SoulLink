# The Gen 3 rollback bundle — frozen at master `7957c24c`

Card **C4-RB** (G4 item 7, `docs/gen3/G4_request_draft.md:110-112`), against `docs/gen3/PLAN.md:228-230`
(§9). Documentation and verification only: nothing was built, patched, launched or committed to
produce this file. Every claim below carries the command or the file:line that shows it, and the
commands are re-runnable read-only (appendix A).

The bundle is **the current pre-G4 shipped Gen 3 experience**: the old Gen 3 client plus the
shipped `SLink-RR.ups` with the md5 it actually produces. It is not the rewrite under
`lua/gen3/`, which is unreleased.

---

## 1. The frozen cut

| Item | Value | How it was read |
|---|---|---|
| Commit | `7957c24c1daf8f17afb5651d4d1391a4d24e43cc` | `git -C "E:/Google Drive/SLink" rev-parse master` |
| Date / subject | 2026-09-22 — "tests: the pureRGB overlay row runs 20 duo scenarios" | `git log -1 --format='%h %ad %s' --date=short master` |
| Release tag | **none exists** | `git tag --sort=-creatordate \| head` returns `archive/*` workstream tags only (newest: `archive/codex/gen2-production` @ `a35c657f`, 2026-09-22) |

`git describe --tags master` → `archive/claude/ui-followups-40f67b-16-g7957c24c`: the nearest tag is a
workstream archive sixteen commits back, and `git tag --contains master` is empty. **There is no
release tag to cross-check against**, so the freeze reference is the commit sha, not a tag. The
release zip's own name comes from a CLI argument (`tools/make_release.py:344`, `zip_name =
f"SLink-player-{version}.zip"`), so no version string is recorded anywhere in the repo either.

The branch under development (`claude/gen3-migration-planning-5d8e45`, tip `63320f96` at the time of
writing) is **not** the shipped experience; §5 lists what it adds.

---

## 2. The old Gen 3 client at the cut — file list and blob shas

All shas from `git ls-tree master -- <path>`; all line numbers are at `7957c24c`.

### 2.1 Entry point and the client itself

| Path | Blob | Role |
|---|---|---|
| `lua/slink.lua` | `a717f813a6ab255af5e0a54bcd735f87a11c530a` | Universal launcher. GBA falls through the Gen 1 block to `game_detect`, then `_CLIENT_MAP.gen3_frlge = "clients/gen3_frlge_client.lua"` (`:95`) and `dofile(_dir .. client_path)` (`:106`). |
| `lua/clients/gen3_frlge_client.lua` | `3fd310c2d488c6d4b8d50439bf0e17659103ddd6` | The production Gen 3 client (FRLG / Emerald / Radical Red). |
| `lua/slink_gen3.lua` | `b16273d4…` (master tip blob; see §5 — the branch changes it) | Manual Gen 3 launcher: `dofile(_dir .. "clients/gen3_frlge_client.lua")`. |

### 2.2 The client's require closure (traced, not guessed)

`lua/clients/gen3_frlge_client.lua` at master sets `package.path` to `lua/`, `lua/games/` and
`data/games/gen3_frlge/` (`:82-86`) and then loads:

| Require site | Module | Blob |
|---|---|---|
| `:100` | `lua/memory_gba.lua` | `3a41e128340dc118e868fe9b9b32f79f779c827e` |
| `:101` | `lua/connector.lua` | `5d71988a1d07f953f3ef74688d27f13a71ba7834` |
| `:102` | `lua/hud.lua` | `a6b71c9677b6a4bc070446408d3f7eff56a88f3b` |
| `:104` (pcall) | `lua/mailbox.lua` | `8c6954c697fccd7b1d79618bbff82467b7444556` |
| `:145` (pcall) | `lua/peer_ghost_npc.lua` | `665edfc78c4d92206250247711f6702f8263203f` |
| `:162` | `lua/game_detect.lua` | `23647fb650bc2a7de8f92cc63e202cacf0ac5d65` |
| `:386` | `lua/sfx_arbiter.lua` | `fd12474ad5d0811c0709ee63113832924ab65440` |

Transitive: `lua/connector.lua:28` requires `socket` → `lua/socket.lua`
(`a4cf196767615e9f118d25d90660f63757d04b4a`) → the LuaSocket binary
`lua/x64/socket-windows-5-4.dll` (`896b3cbacd5e05ed2d5f5b4e02b61d33dd8a3e82`); `lua/mailbox.lua:109`
requires `memory_gba`; `lua/memory_gba.lua:216` requires `game_detect` from inside a function.

The **game module** is not required by name: `game_detect.detect()` returns it and the client uses
`detected.module` (`lua/clients/gen3_frlge_client.lua:164`), i.e. `lua/games/gen3_frlge.lua`
(`138223a17beaae04ad30d510f1fe6f36872e009d`). That module resolves its tables by name
(`require("gen3_frlge_areas")` / `gen3_frlge_locations`, `lua/games/gen3_frlge.lua:594` and `:600`),
so the bundle also needs:

| Path | Blob |
|---|---|
| `data/games/gen3_frlge/gen3_frlge_areas.lua` | `5a224f5892d47f051b6098ab43c3070f298d2c7d` |
| `data/games/gen3_frlge/gen3_frlge_locations.lua` | `3b7738eb17350b80f2c0177e3c94927a3d050f74` |

`lua/json_codec.lua` (`d06f4454ef0aae82885a925cf476c383e806a880`) ships in the same manifest
(`tools/make_release.py`, `_LUA_ROOT`) but is not in the old client's require list.

### 2.3 What the release packaging takes from that list

`tools/make_release.py` at master is the authority for the zip: `_LUA_ROOT` (includes `slink.lua`,
`slink_gen3.lua`, `connector.lua`, `game_detect.lua`, `hud.lua`, `memory_gba.lua`, `sfx_arbiter.lua`,
`socket.lua`, `json_codec.lua`, `mailbox.lua`, `peer_ghost_npc.lua`), `_LUA_CLIENTS` (includes
`gen3_frlge_client.lua`), `_LUA_GAMES` (includes `gen3_frlge.lua`),
`_DATA_GAME_LUA["gen3_frlge"]` = the two tables above, `_LUA_X64_OPTIONAL =
["socket-windows-5-4.dll"]`, and `_COMPANION_UPS = "patch/dist/SLink-RR.ups"` bundled as
`companion/SLink-RR.ups` when `--with-patch`/`--rom` is given (`:440`). Zip layout is
`SLink-player-<version>/lua/...`, `data/games/<gen>/...`, `companion/...`, plus
`PLAYER_SETUP.md` (`:404`, `:411-462`).

Minor: the comment above `_LUA_X64_OPTIONAL` says the DLL is "excluded from git", but it **is**
tracked (`git ls-files lua/x64` lists it; blob `896b3cba…`). Stale comment, no functional impact.

---

## 3. The companion artifact: `SLink-RR.ups`

### 3.1 Identity (measured on this machine, against the tracked blob)

| Property | Value |
|---|---|
| Path in repo | `patch/dist/SLink-RR.ups` — **tracked**, blob `ad3bd7ac3de4113c8af03fa06287aeec8ab26e72`, 12570 bytes; the working copy is byte-identical to the blob (`git diff --stat -- patch/dist/SLink-RR.ups` empty) |
| File md5 | `84082ec350aca89a0fd0dbd9fcea7752` |
| File sha1 / sha256 | `0a085f9218a791626ef26f33307e9f5a238a6d7f` / `3baf01003de0e851001134683d990b8db915b9fa9d39f4a0009cbabca4cfdf08` |
| Clean base it admits | `patch/build/rr_clean.gba`, md5 `8529f3a45d32bce4da637976fcf269d4` — **matches** `server/patcher.py:71` `base_md5` |
| Result of applying it | md5 **`bf8e94a01c0aee0aa7eb37c7333329af`** |
| Same result, as a built ROM | `patch/build/slink_RR.gba`, md5 `bf8e94a0…`, sha1 `b7d1e0756fcc66575878affc8f7b95c45386bb1c` — the sha1 the G2 report records (`docs/gen3/G2_report_2026-09-21.md:33`) |

Both `.gba` files are **untracked** (`patch/.gitignore:3` ignores `build/`), so the base dump is not
archivable from the repo; only its md5 is recorded here, and the bundle must state that the user's
own clean Radical Red 4.1 dump must hash to `8529f3a4…` for the patch to be admitted (the UPS embeds
the source CRC32 — `patch/README.md:19-21`).

### 3.2 The mismatch: the advertised md5 is not what the artifact produces

| Where | Recorded value |
|---|---|
| `server/patcher.py:72` (master, `TARGETS["rr"]["patched_md5"]`) | `8dcffce7659be02474dfa0f876639f8a` |
| `patch/README.md:27` (master) | `8dcffce7659be02474dfa0f876639f8a` |
| `docs/gen3/PLAN.md:230` (§9, "patched md5 `8dcffce7…`") | `8dcffce7…` — agrees with master |
| **What `patch/dist/SLink-RR.ups` actually produces** | **`bf8e94a01c0aee0aa7eb37c7333329af`** |

So the card's premise is only half right: §9's md5 is *not* stale relative to `server/patcher.py` at
the frozen cut — the two agree. What is stale is **both of them relative to the shipped artifact**:
applying the tracked patch to the tracked-pin base yields `bf8e94a0…`, not `8dcffce7…` (appendix A.3,
in-process `ups_apply`, no files written).

Nothing in the suite can see this:

* `tests/unit/test_patcher_routes.py:168-175` — `test_applying_the_shipped_ups_reproduces_the_recorded_md5`
  is parametrized **only** `("rb-red","gen1_red.gb")` and `("rb-blue","gen1_blue.gb")`. The RR apply
  path has no such test.
* `tests/unit/test_patcher_routes.py:106-114` — `test_md5_constants_match_readme` only asserts that
  `server/patcher.py` and `patch/README.md` agree **with each other**, which they do.

Provenance, for the record: `8dcffce7…` was introduced 2026-07-25 17:35 by `134f007b`, the same
commit that committed a **10840-byte** `SLink-RR.ups`; that committed blob yields
`1ad1f84cd73fbe1d7c1a2a5b928a2b63`, i.e. it did not match the pin either. The artifact on disk today
is the **12570-byte** rebuild whose mtime is 2026-07-25 22:25:10, six seconds after
`patch/build/slink_RR.gba` (22:25:06) — i.e. the artifact and the ROM it produces were written
together, hours *after* the commit that pinned `8dcffce7…`. The branch corrected the pin — `72dffad0`: *"companion md5 pin corrected
to what the shipped SLink-RR.ups produces (bf8e94a0, was stale 8dcffce7)"* — and updated
`patch/README.md:27` in the same commit.

**The bundle therefore records both numbers and treats the measured one as authoritative:**

> `SLink-RR.ups` = file md5 `84082ec350aca89a0fd0dbd9fcea7752`, producing the patched ROM
> `bf8e94a01c0aee0aa7eb37c7333329af` from a clean dump `8529f3a45d32bce4da637976fcf269d4`.
> The value advertised at the frozen cut (`8dcffce7…`) is **stale** and must not be used to validate
> the artifact.

Whether `8dcffce7…` was ever a real build on this machine is unresolved (§6) — no file on disk
hashes to it.

This one is **user-visible**, not merely internal: `patch/README.md:27` tells a player their patched
ROM's md5 "should be `8dcffce7…`", so a player who follows the README today sees `bf8e94a0…` and
reasonably concludes the patch or their dump is wrong. The patcher page echoes the same number
(`server/patcher.py:171-172`, `patched_rom_md5`).

---

## 4. How to perform the rollback

Not executed here; this is the procedure and its checklist. `R` = repo root.

### 4.1 Restore the route (the only code change that matters)

The branch's `lua/slink.lua` change is **pure insertion** — `git diff --numstat master...<branch> --
lua/slink.lua` is `61 0`: a `-- ── Gen 3 route ──` block inserted between the Gen 1 block and
`-- Detect which game is loaded`, which on `emu.getsystemid() == "GBA"` dofiles `lua/gen3/entry.lua`,
admits the pack, and on `Entry.ROUTED[pack] and admitted.admitted_by ~= "header"` (with a BizHawk
≥ 2.11 guard) runs `lua/gen3/run.lua` and **returns** before `game_detect`.

1. `git checkout master -- lua/slink.lua` (or revert the block). After this, every GBA cartridge
   falls through to `game_detect` → `_CLIENT_MAP.gen3_frlge` → `clients/gen3_frlge_client.lua`.
2. `git checkout master -- lua/slink_gen3.lua`. The branch changed its last line from
   `dofile(_dir .. "clients/gen3_frlge_client.lua")` to `dofile(_dir .. "slink.lua")`
   (`git diff --numstat master...<branch> -- lua/slink_gen3.lua` = `5 1`). Leaving the branch version
   still works on master's `slink.lua` (it reaches the same client through `game_detect`), but it is
   not the frozen configuration and it is one indirection away from the route the bundle froze.
3. Delete nothing else: the old client's closure (§2) is unchanged on the branch.

### 4.2 Rebuild the zip with the frozen manifest

Use master's `tools/make_release.py` (`git checkout master -- tools/make_release.py`). The branch's
version adds `_LUA_GEN3`, `_LUA_CORE` and two new `_DATA_GAME_LUA` groups (`gen3_frlg`, `gen3_rr`) to
the manifest and to the zip (`git diff master...<branch> -- tools/make_release.py` = `50 0`).

The rolled-back zip must contain exactly:

* `lua/` root list, `lua/gen1/*`, `lua/clients/*` (incl. `gen3_frlge_client.lua`), `lua/games/*`
  (incl. `gen3_frlge.lua`), `lua/x64/socket-windows-5-4.dll`, `data/games/*` per `_DATA_GAME_LUA`
  (incl. `data/games/gen3_frlge/gen3_frlge_{areas,locations}.lua`), `PLAYER_SETUP.md`;
* with `--with-patch`: `companion/SLink-RR.ups` + `companion/COMPANION_PATCH.md`;
* and it must contain **no** `lua/gen3/`, **no** `lua/core/`, **no** `data/games/gen3_frlg/`,
  **no** `data/games/gen3_rr/`.

### 4.3 Companion pair

Ship `patch/dist/SLink-RR.ups` as it is at the cut (file md5 `84082ec3…`); if a pre-patched ROM is
bundled for a playgroup, use the `bf8e94a0…` / sha1 `b7d1e075…` build. The client and the patch are a
pair: the frozen client gates every native feature on the patch's beacon and its ABI version
(`lua/mailbox.lua:14-15` — `MB.SIG = 'SLNK'`, `MB.ABI = 1`; `lua/clients/gen3_frlge_client.lua:111`
`patch_present()`), so do not mix the frozen client with a patch built from the branch's `patch/src`
(the C5 stack has uncommitted `patch/src/handlers.c` changes, §5.2).

### 4.4 Saves

PLAN §9 (`docs/gen3/PLAN.md:230`) is explicit: *a route flag alone is not a rollback because saves
may have been mutated*, and duo attempts run on per-attempt copies of the fixtures. A rollback of the
code does not roll back a save that the new client already wrote to.

### 4.5 Verification checklist (to run at rollback time, not now)

1. Zip listing: no `lua/gen3/`, no `lua/core/`, no `data/games/gen3_frlg/`, no `data/games/gen3_rr/`
   entries; `lua/clients/gen3_frlge_client.lua` present.
2. `lua/slink.lua` in the zip contains no `Gen 3 route` block and its `_CLIENT_MAP` maps
   `gen3_frlge → clients/gen3_frlge_client.lua`.
3. `md5sum` the bundled `companion/SLink-RR.ups` → `84082ec350aca89a0fd0dbd9fcea7752`.
4. Apply it to a clean dump that hashes to `8529f3a4…` and check the result. **Expect
   `bf8e94a01c0aee0aa7eb37c7333329af`.** If it equals `8dcffce7…` instead, the artifact has been
   swapped for a different build — re-freeze rather than assume. Do **not** "fix" a mismatch by
   editing `server/patcher.py`'s pin: that is what left the two out of step in the first place.
5. Load the patched ROM in BizHawk 2.11+ with the frozen client and confirm the client's console log
   shows the old client (no `[SLink] Gen 3 route:` line, which only the branch's block prints).

---

## 5. What the new branch changed that a rollback must undo

### 5.1 Committed on the branch

Merge base is `c411b2f3b68883bd76ba3793e7ca1bca889fe2fa`, i.e. **not** master: the branch merged
master at `ff9b9b95`. `git diff --stat master...<branch> -- <paths>` therefore mixes branch work with
master-side commits after the merge base; the "what to undo relative to what ships today" view is the
two-dot `git diff --stat master <branch> -- <paths>` (same file set here, slightly different counts on
`server/state.py`: `7` vs `14` added lines).

Release-relevant paths (`git diff --numstat master...<branch> -- …`):

| Path | +/- | Note |
|---|---|---|
| `lua/slink.lua` | +61 / −0 | the Gen 3 route block (§4.1) |
| `lua/slink_gen3.lua` | +5 / −1 | launcher now dofiles `slink.lua` |
| `server/patcher.py` | +1 / −1 | the RR md5 pin correction (§3.2) |
| `tools/make_release.py` | +50 / −0 | `_LUA_GEN3`, `_LUA_CORE`, two new data groups, zip writes |
| `server/server.py` | +304 / −43 | Gen 3 admission/status work |
| `server/state.py` | +7 / −0 | (two-dot: +14/−1) |
| `server/manager.py` | +6 / −1 | labels |
| `server/adapters/__init__.py`, `base.py`, `gen3_frlge.py`, **new** `gen3_codec.py` (+903) | | adapter registry + the PYDEC codec |
| new `lua/gen3/*` (12 files, ~4.7k lines incl. `client.lua` 1220, `reads.lua` 559, `boxes.lua` 521), new `lua/core/*` (3 files) | | the rewrite; `shadow_run.lua` is deliberately excluded from the release manifest |
| new `data/games/gen3_frlg/*` (4 files) and `data/games/gen3_rr/*` (4 files) | | the new packs |
| `tools/*` new (`build_pret_gba_syms.py`, `gba_map.py`, `gen3_fixtures.py`, `gen3_pins.py`, `gen3_reads_pydec.py`, `gen3_shadow_*.py`), `tools/e2e_duo.py` +1521/−14 | | dev/verification tooling |

`data/games/gen3_frlge/*` is **unchanged** on the branch (`git diff --numstat master...<branch> --
data/games/gen3_frlge` is empty), so the shipped FRLG tables in a rollback are master's blobs.

### 5.2 Uncommitted in the worktree (in flight — not part of any bundle)

At the time of writing the worktree carries an uncommitted C5 stack: `lua/gen3/client.lua` (+238/−12),
`lua/gen3/native.lua` (+48/−10), `lua/gen3/run.lua` (+126), `lua/gen3/entry.lua` (+4),
`lua/mailbox.lua` (+5), `patch/src/handlers.c` (+67/−11), `patch/src/ADDRESSES.md` (+33),
`server/state.py` (+107/−6). These are the rewrite's own in-progress changes; the frozen bundle is
master's files and nothing from this list.

---

## 6. Mismatches and open items (the flags)

1. **RR companion md5 (finding, not a fix-it item).** The artifact's measured result
   (`bf8e94a0…`) differs from the value the frozen cut advertises (`8dcffce7…` in
   `server/patcher.py:72`, `patch/README.md:27`, `docs/gen3/PLAN.md:230`), and no test covers the RR
   apply path. The branch's `72dffad0` already corrected the pin; the correction is not in master.
2. **No release tag exists**, so "the last release" cannot be cross-checked the way the card asked;
   the commit sha is the reference.
3. `tools/make_release.py`'s "DLL … excluded from git" comment is stale (the DLL is tracked).
4. `patch/build/*.gba` are untracked, so the base dump is not archivable from the repo — the bundle
   records its md5 only.
5. PLAN §9's `8dcffce7…` is not stale *relative to master*; it is stale relative to the artifact.
   Worth correcting in the plan's text when the pin is next touched.

## Appendix A — reproduction commands (read-only)

```bash
# A.1 the cut and the tag question
git -C "E:/Google Drive/SLink" rev-parse master
git -C "E:/Google Drive/SLink" tag --sort=-creatordate | head
git -C "E:/Google Drive/SLink" describe --tags master
git -C "E:/Google Drive/SLink" tag --contains master      # empty

# A.2 the bundle's file list
for p in lua/slink.lua lua/slink_gen3.lua lua/clients/gen3_frlge_client.lua lua/memory_gba.lua \
         lua/games/gen3_frlge.lua lua/mailbox.lua lua/peer_ghost_npc.lua lua/connector.lua \
         lua/socket.lua lua/hud.lua lua/game_detect.lua lua/sfx_arbiter.lua lua/json_codec.lua \
         lua/x64/socket-windows-5-4.dll data/games/gen3_frlge/gen3_frlge_areas.lua \
         data/games/gen3_frlge/gen3_frlge_locations.lua; do
  git -C "E:/Google Drive/SLink" ls-tree master -- "$p"
done

# A.3 the artifact, its hashes, and what it produces (in-process; writes nothing)
md5sum patch/dist/SLink-RR.ups; sha1sum patch/dist/SLink-RR.ups; sha256sum patch/dist/SLink-RR.ups
md5sum patch/build/rr_clean.gba patch/build/slink_RR.gba; sha1sum patch/build/slink_RR.gba
python - <<'PY'
import hashlib, importlib.util
spec = importlib.util.spec_from_file_location("make_ups", "patch/tools/make_ups.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
out = mod.ups_apply(open("patch/build/rr_clean.gba","rb").read(),
                    open("patch/dist/SLink-RR.ups","rb").read())
print(hashlib.md5(out).hexdigest())      # bf8e94a01c0aee0aa7eb37c7333329af, not 8dcffce7...
PY

# A.4 the advertised values at the cut, and the coverage gap
git -C "E:/Google Drive/SLink" show master:server/patcher.py | sed -n '66,74p'
git -C "E:/Google Drive/SLink" show master:patch/README.md | sed -n '19,27p'
git -C "E:/Google Drive/SLink" show master:tests/unit/test_patcher_routes.py | sed -n '166,176p'

# A.5 what a rollback must undo
git -C "E:/Google Drive/SLink/.claude/worktrees/gen3-migration-planning-5d8e45" \
    diff --numstat master...HEAD -- lua/slink.lua lua/slink_gen3.lua server/ tools/make_release.py
```
