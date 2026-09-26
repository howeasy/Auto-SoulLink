--[[
  lua/tests/duo/scenario_gen2_type_clause.lua -- the gen2_new `type_clause` scenario (D-5 type). Gen 1 reference:
  type_clause_new (duo_gen1_main.lua). Body, facts (with file:line citations) and verdict: gen2_clause.lua.

  Both halves play the `link` body unchanged (CONTINUE, hello, go-file, one Route 29 catch, native save)
  against a server started with --type-clause, read their verdict off the wire, then save natively again.
  Unlike Gen 1 Route 1, Route 29 is not all one type: Crystal morn/day Hoppip (GRASS/FLYING) pairs clean with
  Sentret/Rattata (NORMAL), so a Crystal-side pair can link with no clause (P = 2 x 5% x 45% = 4.5% on C<->C
  day). Every G/S Route 29 species carries NORMAL, so on G<->S the clause always fires.

  MARKER CONTRACT (after everything `link` prints except RECEIPT; JSON after the tag):
    CLAUSE_CAPTURE {frame, key, species_id, area_id, types, gender}   after CAUGHT
    CLAUSE_VERDICT {frame, verdict}   rejected       (RX force_faint key=<own key>) this half captured second
                                      partner_rejected (RX play_sound sound=22)       the partner was rejected
                                      linked         (RX msgbox + RX_TEXT "... linked!") no clause; a Pidgey or
                                                     Hoothoot catch can never link (it shares a type with all)
    rejected only: RX memorialize key=<own>, RX play_sound sound=26, RX unresolve_area area_id=<catch area>,
                   RX gui_prompt + RX_TEXT "[x] Type clause: shared <types>" (every named type is the catch's),
                   PARTY_HP_WRITE {key=<own>, ok=true} (the production bench faint), MEMORIAL_ACK {key=<own>},
                   REJECTED_MON {frame, key, ending "dead" (memorialize_failed: in_party, hp 0, slot, status) |
                                 "memorial" (memorialize_done: box 13, in_party false)}
    SAVE_WITNESS    the final native save, after CLAUSE_VERDICT (and REJECTED_MON)
    RECEIPT {schema "gen2-duo-type-clause-v1", clause "type", verdict, ending, path, species_id, types, gender,
             ...link receipt}   path = clause_observed | clause_unobserved (linked; the lane may retry)
    RESULT: PASS|FAIL "type clause <verdict> <key> (<path>)"
  Server-side oracle (links.json/events): one PENDING retry area for the rejected half or one ALIVE link.
--]]
local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
return dofile(here .. "gen2_clause.lua").scenario("type")
