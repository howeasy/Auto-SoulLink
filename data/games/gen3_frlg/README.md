# `gen3_frlg` pack

Generated. Do not hand-edit anything here — run `python tools/gen_gen3_profile.py`
(`--check` is the P2 exit condition "profile diff = 0 vs today's literals").

## `profile.json`

First cut (P2 card C2-2). The only source of today's addresses is the literal table
`GEN3.profiles.vanilla` in `lua/games/gen3_frlge.lua`; the generator parses that Lua text
directly (no Lua runtime) so nothing is re-typed. `source.git_head` is the last commit that
touched that file and `source.sha256` its content hash, so a change there makes `--check` fail.

Per title: `ram` (EWRAM/IWRAM), `rom` (ROM addresses incl. `SE_SONG_HEADERS`, `BASESTATS_ADDR`,
the `CB2_*` callbacks), `derived` (sizes, offsets, counts, modes and flags), plus `rom_thumb` —
the `rom` keys whose literal already carries the Thumb bit. Those values are kept **verbatim**:
`gTasks[].func` and `gMain.callback2` are read out of RAM with the `+1`, so stripping the bit
here would make the profile disagree with what the client compares.

| title | Lua table | admitted | `rom_sha1` |
|---|---|---|---|
| `firered` | `vanilla` | yes | `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` |
| `leafgreen` | `vanilla` | yes | `574fa542ffebb14be69902d1d36f1ec0a4afd71e` |
| `firered_ap` | `ap` | **no** | — |
| `emerald` | `emerald` | **no** | — |

### LeafGreen divergence is UNVERIFIED

`leafgreen` is byte-for-byte the FireRed profile, because `lua/games/gen3_frlge.lua` has one
`vanilla` table serving both BPRE and BPGE. Whether any LG address actually diverges from FR has
**not** been established. Pinning LG's own addresses (or proving equality against a pret/LG build)
is **P2 card C2-3**; until it closes, every LG row in `docs/gen3_requirements.md` inherits that
caveat and the pack is not evidence that LG is covered.

### Unadmitted titles

`firered_ap` (Archipelago) and `emerald` are carried verbatim so no data from the old client's
table is lost (PLAN §5.1: "`emerald`/`ap` profiles remain in the packs as unadmitted titles").
`admitted: false` is the machine-readable form of that; the client refuses them by name.
Their addresses were never re-verified for this pack and carry no ROM hash.
