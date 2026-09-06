# Rival refresh stage boundary

The public post-native `memory_gba.refreshEnemyPartyNative` reset seven bytes
starting at BattlePokemon+18. RR's actual stage range is+19..+1F. The old loop
overwrote the third-type byte and left evasion unchanged. Controlled singles and
doubles calls reproduced an evasion stage12 surviving a replacement while the
other six stages became6. The reset now uses the existing named stage offset.

The exact admitted RR primitive090A0608 independently confirms the range: it
reads gBattlersCount at02023BCC, starts at02023BFD (`gBattleMons+19`), writes7 bytes
of6 and advances by88 per battler. Unstubbed CPU cases for2 and4 battlers preserve
every surrounding byte, including type3, and reset evasion. This agrees with the
vendored CFRU `BattlePokemon` declaration and the existing Lua stage reader.

Two unchanged-Lua regressions failed before the fix and pass afterward; two
exact-ROM CPU cases also pass. The tests do not establish fresh paired party
selection, scene execution, complete native replacement readback or durable rival
acknowledgement. Third-type initialization for an entirely new battle projection
remains the engine/lifecycle participant's responsibility; a stage reset cannot
write a type as a side effect.

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -q -p no:faulthandler tests/rr/native/test_rival_stat_stages_cpu.py tests/rr/runtime/test_rival_stat_stage_refresh.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```
