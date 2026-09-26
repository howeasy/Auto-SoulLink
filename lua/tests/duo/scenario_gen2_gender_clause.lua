--[[
  lua/tests/duo/scenario_gen2_gender_clause.lua -- the gen2_new `gender_clause` scenario (D-5 gender). No Gen 1
  reference (Gen 1 has no gender); server --gender-clause. Body, facts (with file:line citations) and verdict:
  gen2_clause.lua.

  Both halves play the `link` body unchanged against a server started with --gender-clause, read their verdict
  off the wire, then save natively again. Every Route 29 species is GENDER_F50 (127): a catch is FEMALE iff its
  Attack DV <= 7 (GetGender, C engine/pokemon/mon_stats.asm:124-230 / G :126-232; the server's gender_from_key,
  server/adapters/gen2_gsc.py:258-272). The clause fires on about half of all pairs; the other half link
  (path clause_unobserved) and the lane may retry the whole scenario.

  MARKER CONTRACT: exactly scenario_gen2_type_clause.lua's, with
    CLAUSE_CAPTURE.gender   the catch's gender from its key (the verdict recomputes it)
    rejected prompt         "[x] Gender clause: both are ♂" (male) | "♀" (female): the catch's own gender
    RECEIPT.schema          "gen2-duo-gender-clause-v1", clause "gender"
    RESULT: PASS|FAIL "gender clause <verdict> <key> (<path>)"
--]]
local here = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
return dofile(here .. "gen2_clause.lua").scenario("gender")
